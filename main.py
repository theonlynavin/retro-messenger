import os
import json
import time

from retro_ui import (
    RetroMessengerUI,
    AppState
)

from client_app import ClientApplication


CONTACTS_FILE = "contacts.json"
CHATS_FILE = "chats.json"


# =========================
# PERSISTENCE
# =========================

def load_contacts(filename):
    if not os.path.exists(filename):
        return {}

    with open(filename, "r") as f:
        raw = json.load(f)

    clean = {}

    for user_k, contacts in raw.items():
        try:
            user_id = int(user_k)
        except (ValueError, TypeError):
            continue

        clean[user_id] = {}

        for cid_k, name in contacts.items():
            try:
                cid = int(cid_k)
            except (ValueError, TypeError):
                continue

            clean[user_id][cid] = name

    return clean


def save_contacts(filename, contacts):
    to_save = {}

    for user_id, user_contacts in contacts.items():
        to_save[str(user_id)] = {}
        for cid, name in user_contacts.items():
            to_save[str(user_id)][str(cid)] = name

    with open(filename, "w") as f:
        json.dump(to_save, f)


def load_chats(filename):
    if not os.path.exists(filename):
        return {}

    with open(filename, "r") as f:
        raw = json.load(f)

    clean = {}

    for user_k, conversations in raw.items():
        try:
            user_id = int(user_k)
        except (ValueError, TypeError):
            continue

        clean[user_id] = {}

        for other_k, messages in conversations.items():
            try:
                other_id = int(other_k)
            except (ValueError, TypeError):
                continue

            if isinstance(messages, list):
                clean_msgs = []
                for msg in messages:
                    if not isinstance(msg, (list, tuple)):
                        continue

                    # Old format: (direction, text)
                    if len(msg) == 2:
                        direction, text = msg
                        ts = time.time()  # fallback timestamp
                        clean_msgs.append((direction, text, ts))

                    # New format: (direction, text, ts)
                    elif len(msg) == 3:
                        direction, text, ts = msg
                        clean_msgs.append((direction, text, ts))

                clean[user_id][other_id] = clean_msgs
            else:
                clean[user_id][other_id] = []

    return clean


def save_chats(filename, chats):
    to_save = {}

    for user_id, conversations in chats.items():
        to_save[str(user_id)] = {}

        for other_id, messages in conversations.items():
            to_save[str(user_id)][str(other_id)] = messages

    with open(filename, "w") as f:
        json.dump(to_save, f)


# =========================
# ENTRY POINT
# =========================

if __name__ == "__main__":

    host = "messenger-s0tl.onrender.com"

    # Load persistent data
    all_contacts = load_contacts(CONTACTS_FILE)
    all_chats = load_chats(CHATS_FILE)

    # Create state object
    state = AppState(
        contacts=all_contacts,
        chats=all_chats
    )

    # Network factory
    def app_factory(client_id):
        return ClientApplication(host, client_id)

    # Persistence hooks
    def persist_contacts():
        save_contacts(CONTACTS_FILE, state.contacts)

    def persist_chats():
        save_chats(CHATS_FILE, state.chats)

    # Launch UI
    ui = RetroMessengerUI(
        state=state,
        app_factory=app_factory,
        save_contacts=persist_contacts,
        save_chats=persist_chats
    )

    ui.start()