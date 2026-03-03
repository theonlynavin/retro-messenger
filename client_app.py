from client_http import ClientHTTP
import logging

from cryptography.fernet import Fernet
import base64
import hashlib

class ClientApplication:
    def __init__(self, host, client_id, association_retries=3):
        self.host = host
        self.client = ClientHTTP(host)
        self.client_id = client_id
        self.associated = False
        self.association_retries = association_retries
        self._logger = logging.getLogger(__name__)
        shared_secret = b"RETRO_EE5150_MESSENGER"
        derived = hashlib.sha256(shared_secret).digest()
        fernet_key = base64.urlsafe_b64encode(derived)
        self.cipher = Fernet(fernet_key)

    def _send(self, payload):
        return self.client.request(payload)

    def associate(self):
        response = self._send({
            "type": 0,
            "message": "ASSOCIATE",
            "id": self.client_id
        })

        for _ in range(self.association_retries):
            if response.get("type") == 0 and response.get("message") == "ASSOCIATE_SUCCESS":
                self.associated = True
                return
            elif response.get("type") == 0 and response.get("message") == "ASSOCIATE_FAILED":
                self.associated = False
                continue        

        raise Exception(f"Association failed: {response}")

    def _ensure_associated(self):
        if not self.associated:
            self.associate()

    def _handle_association_failure(self, response):
        if response.get("type") == 0 and response.get("message") == "ASSOCIATE_FAILED":
            self.associated = False
            self.associate()
            return True
        return False
    
    def get_message(self):
        self._ensure_associated()

        payload = {
            "type": 1,
            "message": "GET",
            "id": self.client_id
        }

        response = self._send(payload)

        # Re-association phase
        if self._handle_association_failure(response):
            response = self._send(payload)

        msg_type = response.get("type")
        msg_text = response.get("message")

        if msg_type == 2 and msg_text == "GET_RESPONSE":
            payload = response.get("payload")
            if payload.startswith("ENC:"):
                ciphertext = payload[4:]
                decrypted = self.cipher.decrypt(ciphertext.encode())
                response["payload"] = decrypted.decode()
            else:
                response["payload"] = payload

            return response
        
        if msg_type == 1 and msg_text == "BUFFER_EMPTY":
            return None

        raise Exception(f"Unexpected GET response: {response}")

    def push_message(self, recipient_id, content : str):
        self._ensure_associated()
        encrypted = "ENC:" + self.cipher.encrypt(content.encode()).decode()

        payload = {
            "type": 2,
            "message": "PUSH",
            "id": self.client_id,
            "id2": recipient_id,
            "length": len(encrypted),
            "payload": encrypted
        }

        response = self._send(payload)

        # Re-association phase
        if self._handle_association_failure(response):
            response = self._send(payload)

        msg_type = response.get("type")
        msg_text = response.get("message")

        if msg_type == 2 and msg_text == "PUSH_SUCCESS":
            return True

        if msg_type == 2 and msg_text == "BUFFER_FULL":
            return False

        if msg_type == 2 and msg_text == "INVALID_LENGTH":
            raise Exception("Invalid message length")

        if msg_type == 0 and msg_text == "MALFORMED_FRAME":
            raise Exception("Malformed frame")

        raise Exception(f"Unexpected PUSH response: {response}")
