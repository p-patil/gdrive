from argparse import ArgumentParser
from pathlib import Path

from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
from pydrive.files import ApiRequestError, GoogleDriveFile

import os, time

CREDENTIALS_FILE = "./authentication/credentials.json"

def authenticate(credentials_file):
    gauth = GoogleAuth()
    gauth.LoadCredentialsFile(credentials_file)

    if gauth.credentials is None: # Failed to load from cached credentials
        gauth.LocalWebserverAuth() # Creates local webserver and auto handles authentication
    elif gauth.access_token_expired:
        gauth.Refresh()
    else:
        gauth.Authorize()

    gauth.SaveCredentialsFile(credentials_file)

    return gauth

def get_root(drive):
    return drive.ListFile({"q": "'root' in parents and trashed=false"}).GetList()

def download_file(drive, source_path, download_path=None):
    source_path = Path(source_path)
    if download_path is None:
        download_path = Path.home() / source_path

    download_dir, download_file_name = download_path.parent, download_path.name
    if not download_dir.exists():
        download_dir.mkdir(parents=True)

    drive_file = get_file(drive, str(source_path))
    downloaded_drive_file = drive.CreateFile({"id": drive_file["id"]})
    downloaded_drive_file.GetContentFile(str(download_path))

def upload_file(drive, source_path, upload_path):
    source_path, upload_path = Path(source_path), Path(upload_path)
    if not source_path.exists():
        raise ValueError("Source path does not exist")
    source_file_name = source_path.name

    drive_file = get_file(drive, str(upload_path))

    # valid = False
    # try: # Check if upload path points to a directory
        # drive_file = get_file(drive, str(upload_path))
        # if not is_folder(drive_file):
            # valid = True
    # except:
        # valid = True

    # if valid:
    if drive_file is None or not is_folder(drive_file):
        # upload_path points to a file path as expected; get parent directory
        dir_path = upload_path.parent
        if not file_exists(drive, str(dir_path)): # Create directory path if necessary
            create_remote_path(drive, str(dir_path))
        drive_parent_dir = get_file(drive, str(dir_path))
    else:
        drive_parent_dir = drive_file

        # Upload file inside the directory pointed to by upload_path
        upload_path = upload_path / source_file_name

    # Upload file
    parent_id = drive_parent_dir["id"]
    drive_file = drive.CreateFile({
        "parents": [{"kind": "drive#fileLink", "id": parent_id}],
        "title": str(source_file_name)
    })
    drive_file.SetContentFile(str(source_path))
    drive_file.Upload()

def upload_file_fast(drive, source_path, upload_path, drive_parent_dir):
    upload_dir, upload_file_name = upload_path.parent, upload_path.name

    drive_file = drive.CreateFile({
        "title": str(upload_file_name),
        "parents": [{"kind": "drive#fileLink", "id": drive_parent_dir["id"]}]
    })
    drive_file.SetContentFile(str(source_path))
    drive_file.Upload()

def upload_directory_fast(drive, source_path, upload_path, drive_parent_dir):
    source_path, upload_path = Path(source_path), Path(upload_path)
    assert source_path.is_dir()

    drive_dir = create_remote_folder(drive, upload_path, drive_parent_dir)

    for child in source_path.iterdir():
        child_upload_path = upload_path / child.name
        if child.is_dir():
            upload_directory_fast(drive, child, child_upload_path, drive_dir)
        else:
            upload_file_fast(drive, child, child_upload_path, drive_dir)

# TODO(piyush) Switch to using pathlib
def create_remote_path(drive, path):
    folder_names = [name for name in path.split("/") if len(name) > 0]

    # First, move up to the first folder on the path that doesn't already exist remotely
    index = 0
    sub_path = folder_names[0]
    while file_exists(drive, sub_path):
        index += 1
        sub_path += "/" + folder_names[index]

    # Starting at the first folder on the path that doesn't exist, iteratively create folders
    drive_dir = create_remote_folder(drive, sub_path)
    for i in range(index + 1, len(folder_names)):
        sub_path += "/" + folder_names[i]
        drive_dir = create_remote_folder(drive, sub_path)

    return drive_dir

def create_remote_folder(drive, path, drive_parent_dir=None):
    path = Path(path)

    # Get parent directory
    if drive_parent_dir is None:
        drive_parent_dir = get_file(drive, str(path.parent))

    # Set the drive file to be a directory and put it in the parent directory, then upload
    drive_folder = drive.CreateFile({
        "title": str(path.name),
        "parents": [{"id": drive_parent_dir["id"]}],
        "mimeType": "application/vnd.google-apps.folder"
    })
    drive_folder.Upload()

    return drive_folder

def get_file(drive, path):
    path = Path(path)
    parts = path.parts
    if parts[0] == "/":
        parts = parts[1 : ]

    parent_id = "root"
    for directory in parts:
        query = "'%s' in parents and title='%s' and trashed=false" % (parent_id, directory)
        drive_file = drive.ListFile({"q": query}).GetList()
        if len(drive_file) == 0:
            return None # File does not exist
        else:
            drive_file = drive_file[0]
        parent_id = drive_file["id"]

    return drive_file

# TODO(piyush) optimize this
def file_exists(drive, path):
    try:
        get_file(drive, path)
        return True
    except ValueError:
        return False

def get_children(drive, drive_file):
    if not is_folder(drive_file):
        raise ValueError("Trying to obtain children of non-folder file")

    return drive.ListFile({"q": "'%s' in parents and trashed=false" % drive_file["id"]}).GetList()

def is_folder(drive_file):
    return drive_file["mimeType"] == "application/vnd.google-apps.folder"

def get_missing_remote_files(drive, local_path, remote_dir_path, drive_dir):
    """
    Returns files underneath the directory LOCAL_PATH which are not present (based on the same
    relative path) under REMOTE_DIR_PATH remotely. The files are returned as a list of 2-tuples,
    with each tuple composed of (1) a local file path, and (2) a drive object pointing to the
    parent directory of the intended upload location.
    """
    local_path, remote_dir_path = Path(local_path), Path(remote_dir_path)

    print_on_same_line("Processing %s" % str(local_path)) # TODO(piyush) remove

    assert local_path.name == remote_dir_path.name
    assert local_path.exists()
    assert local_path.is_dir()
    assert drive_dir is not None

    to_upload = []
    drive_children_names = {child["title"]: child for child in get_children(drive, drive_dir)}
    for local_child in local_path.iterdir():
        # If matching file (or directory) doesn't exist remotely, mark it for upload.
        if local_child.name not in drive_children_names or \
           local_child.is_dir() != is_folder(drive_children_names[local_child.name]):
            if local_child.is_dir():
                file_paths = [
                    Path(file_name)
                    for _, _, file_names in os.walk(str(local_child))
                    for file_name in file_names
                ]

                if file_paths:
                    print_on_same_line("Adding all files in directory %s" % str(local_child)) # TODO(piyush) remtoe

                    to_upload.extend([(file_path, drive_dir) for file_path in file_paths])
                    # to_upload.extend([(file_path, False) for file_path in file_paths])
                else:
                    print_on_same_line("Adding empty directory %s" % str(local_child)) # TODO(piyush) remove

                    # to_upload.append((local_child, True))
                    to_upload.append((local_child, drive_dir))
            else:
                print_on_same_line("Adding file %s" % str(local_child)) # TODO(piyush) remove

                # to_upload.append((local_child, False))
                to_upload.append((local_child, drive_dir))
        # Otherwise, if matching file does exist remotely, then assuming it's a directory, recurse.
        elif local_child.is_dir():
            to_upload.extend(
                get_missing_remote_files(
                    drive,
                    local_child,
                    remote_dir_path / local_child.name,
                    drive_children_names[local_child.name]))

    return to_upload

def validate_arguments(drive, local_path, remote_path):
    local_path, remote_path = Path(local_path), Path(remote_path)

    # Make sure local path exists and is a directory.
    assert local_path.exists() and local_path.is_dir()

    # Make sure remote path exists.
    assert file_exists(drive, remote_path)

def print_on_same_line(s):
    if "TERM_WIDTH" not in globals():
        global TERM_WIDTH
        TERM_WIDTH = int(os.popen("stty size", "r").read().split()[1])

    # if len(s) <= TERM_WIDTH:
        # print(s + " " * (TERM_WIDTH - len(s)), end="\r")
    # else:
        # print(s, end="\r")

    # Useful ANSI escape sequences
    mul = "\033[1A" # Move up line
    mdl = "\n"      # Move down line
    rts = "\033[1G" # Return to start
    cl = "\033[K"   # Clear line

    print(cl + s, end="")
    if len(s) <= TERM_WIDTH:
        print("\r", end="")
    else:
        print(mul + "\r", end="")

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--local")
    parser.add_argument("--remote")

    args = parser.parse_args()

    drive = GoogleDrive(authenticate(CREDENTIALS_FILE))
    validate_arguments(drive, args.local, args.remote)

    top_drive_dir = get_file(drive, args.remote)
    to_upload = get_missing_remote_files(drive, args.local, args.remote, top_drive_dir)

    # TODO(piyush) remove
    import pickle
    with open("to_upload.pkl", "wb") as f:
        pickle.dump(to_upload, f)

    uploaded, errored = [], []
    for i, (local_path, drive_dir) in enumerate(to_upload):
        print_on_same_line("%i / %i - Uploading %s" % (i + 1, len(to_upload), local_path))

        remote_path = args.remote / local_path.relative_to(args.local)

        try:
            if local_path.is_dir():
                create_remote_folder(drive, remote_path, drive_dir)
            else:
                upload_file_fast(drive, local_path, remote_path, drive_dir)
        except ApiRequestError as e:
            print("Received HTTP error when uploading file %s: %s" % (local_path, str(e)))
            errored.append((local_path, drive_dir, e))
            time.sleep(10) # TODO(piyush) Read the HTTP error to find out how long to wait before trying again
        except ConnectionResetError as e:
            print("Connection was reset by peer before uploading file %s: %s" % (local_path, str(e)))
            drive = GoogleDrive(authenticate(CREDENTIALS_FILE))
            errored.append((local_path, drive_dir, e))
        except:
            print("Received unknown error on file %s: %s" % (local_path, str(e)))
            errored.append((local_path, drive_dir, None))

        uploaded.append((local_path, drive_dir))

    if uploaded:
        with open("uploaded.pkl", "wb") as f:
            pickle.dump(uploaded, f)


    # # TODO(piyush) remove
    if errored:
        with open("errored.pkl", "wb") as f:
            pickle.dump(errored, f)

    # upload_directory_fast(drive, "/home/piyush/research/dawnfellows/adv_maml", "/temp/adv_maml", get_file(drive, "/temp"))

# TODO UPLOAD ADV_MAML
