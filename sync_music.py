import os
from pydrive.drive import GoogleDrive
from pydrive.auth import GoogleAuth

CREDENTIALS_FILE = "/home/piyush/gdrive/credentials.json"

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
    if download_path is None:
        download_path = os.path.expanduser("~/gdrive/" + source_path)

    download_dir, download_file_name = os.path.split(download_path)
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    drive_file = get_file(drive, source_path)
    downloaded_drive_file = drive.CreateFile({"id": drive_file["id"]})
    downloaded_drive_file.GetContentFile(download_path)

def upload_file(drive, source_path, upload_path):
    if not os.path.exists(source_path):
        raise ValueError("Source path does not exist")
    _, source_file_name = os.path.split(source_path)

    valid = False
    try: # Check if upload path points to a directory
        drive_file = get_file(drive, source_path)
        if not is_folder(drive_file):
            valid = True
    except:
        valid = True

    if valid:
        # upload_path points to a file path as expected; get parent directory
        dir_path, _ = os.path.split(upload_path)
        if not file_exists(drive, dir_path): # Create directory path if necessary
            create_remote_path(drive, dir_path)
        drive_parent_dir = get_file(drive, dir_path)
    else:
        drive_parent_dir = drive_file

        # Upload file inside the directory pointed to by upload_path
        if not source_path.endswith("/"):
            upload_path += "/"
        upload_path += source_file_name

    # Upload file
    parent_id = drive_parent_dir["id"]
    drive_file = drive.CreateFile({
        "parents": [{"kind": "drive#fileLink", "id": parent_id}],
        "title": source_file_name
    })
    drive_file.SetContentFile(source_path)
    drive_file.Upload()

def create_remote_path(drive, path):
    folder_names = [name for name in path.split("/") if len(name) > 0]

    # First, move up to the first folder on the path that doesn't already exist remotely
    index = 0
    sub_path = folder_names[0]
    while file_exists(drive, sub_path):
        index += 1
        sub_path += "/" + folder_names[index]

    # Starting at the first folder on the path that doesn't exist, iteratively create folders
    create_remote_folder(drive, sub_path)
    for i in range(index + 1, len(folder_names)):
        sub_path += "/" + folder_names[i]
        create_remote_folder(drive, sub_path)

def create_remote_folder(drive, path):
    # Get parent directory
    parent_dir_path, dir_name = os.path.split(path)
    drive_parent_dir = get_file(drive, parent_dir_path)

    # Set the drive file to be a directory and put it in the parent directory, then upload
    drive_folder = drive.CreateFile({
        "title": dir_name,
        "parents": [{"id": drive_parent_dir["id"]}],
        "mimeType": "application/vnd.google-apps.folder"
    })
    drive_folder.Upload()

def get_file(drive, path):
    if path[0] == "/":
        path = path[1 :]

    parent_id, drive_file = "root", get_root(drive)
    for file_name in path.split("/"):
        query = "'%s' in parents and title='%s' and trashed=false" % (parent_id, file_name)
        drive_file = drive.ListFile({"q": query}).GetList()
        if len(drive_file) == 0:
            return None # File does not exist
        else:
            drive_file = drive_file[0]
        parent_id = drive_file["id"]

    return drive_file

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

if __name__ == "__main__":
    drive = GoogleDrive(authenticate(CREDENTIALS_FILE))

    drive_music_dir = get_file(drive, "/Patil Family/piyush/media/music")
    music_files = get_children(drive, drive_music_dir)
    music_file_name_to_file = {music_file["title"]: music_file for music_file in music_files}

    local_music_dir = "/home/piyush/media/music"
    local_music_file_names = set(os.listdir(local_music_dir))

    to_upload = []
    for local_file_name in local_music_file_names:
        local_file_path = os.path.join(local_music_dir, local_file_name)

        if local_file_name not in music_file_name_to_file:
            to_upload.append(local_file_path)
        else:
            remote_drive_file = music_file_name_to_file[local_file_name]

            local_size = os.path.getsize(local_file_path)
            remote_size = int(remote_drive_file["fileSize"])
            if local_size != remote_size:
                print("Found uploaded file, but sizes differ. Local: %i bytes, remote: %i bytes" % (local_size, remote_size))

    # Sort by ascending file size
    to_upload = sorted(to_upload, key = lambda file_path: os.path.getsize(file_path))

    for i, file_path in enumerate(to_upload):
        _, file_name = os.path.split(file_path)
        print("File %i/%i, uploading \"%s\"" % (i + 1, len(to_upload), file_name))
        upload_file(drive, file_path, "/Patil Family/piyush backup 1-17-18/media/music/%s" % file_name)
