import os

from sfkit.protocol.utils import constants
from src.sfkit.api import get_doc_ref_dict


def auth() -> None:
    """
    Authenticate a GCP service account from the study with the sfkit CLI.
    """

    try:
        with open("auth_key.txt", "r") as f:
            auth_key = f.readline().rstrip()
    except FileNotFoundError:
        print("auth_key.txt not found.")
        auth_key_path = input("Enter the path to your auth_key.txt file: ")
        try:
            with open(auth_key_path, "r") as f:
                auth_key = f.readline().rstrip()
        except FileNotFoundError:
            print("auth_key.txt not found.  Please download the auth_key.txt file from the sfkit website.")
            exit(1)

    os.makedirs(constants.SFKIT_DIR, exist_ok=True)
    with open(constants.AUTH_KEY, "w") as f:
        f.write(auth_key)

    try:
        _, _ = get_doc_ref_dict()  # verify that the auth_key is valid
    except Exception as e:
        os.remove(constants.AUTH_KEY)
        print("Invalid auth_key.txt file.")
        print(e)
        exit(1)

    print("Successfully authenticated!")
