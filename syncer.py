import os
from pydrive.drive import GoogleDrive
from pydrive.auth import GoogleAuth

CREDENTIALS_FILE = os.path.expanduser("~/gdrive/credentials.txt")
HASHES_FILE_NAME = "hashes.p"

def sync(directory, drive_path, diff_by_content=False):
    drive = GoogleDrive(authenticate(CREDENTIALS_FILE))

    hashes_file = get_file(drive, HASHES_FILE_NAME)
    if hashes_file is None:
        hashes = {}
    else:
        # TODO download file and load hashes by unpickling the file
        pass

    drive_directory = get_file(drive, drive_path)

    sync_helper(drive, directory, drive_directory, hashes, diff_by_content)

def sync_helper(drive, directory, drive_directory, hashes, diff_by_content):
    local_files = os.listdir(directory)
    remote_files = get_children(drive, drive_directory)

    local_only, common, remote_only = partition_file_lists(local_files, remote_files, directory)

    local_files_to_upload, local_dirs_to_upload = split_by_file_type(local_only, directory)
    files_to_sync, dirs_to_sync = split_by_file_type(common)
    remote_files_to_delete, remote_dirs_to_delete = split_by_file_type(remote_only)

    for file_name in local_files_to_upload:
        pass # TODO upload file

    for dir_name in local_dirs_to_upload:
        pass # TODO recursively upload directory

    for drive_file in remote_files_to_delete:
        pass # TODO remotely delete file
    for drive_file in remote_dirs_to_delete:
        pass # TODO remotely delete directory recursively

    for drive_file in files_to_sync:
        pass # TODO check local file against remote file, using hashes or downloading and directly comparing if necessary, and upload local file (deleting remote file) if necessary
    for drive_dir in dirs_to_sync:
        sync_helper(drive, os.path.join(directory, drive_file["title"]), drive_dir, hashes, diff_by_content)

def split_by_file_type(file_list, local_directory=None):
    """
    Given a list of files and whether the the files are local or drive files, splits into regular
    files and directories.
    """
    if local_directory is not None:
        file_list = {
            (file_name, os.path.isdir(os.path.join(local_directory, file_name))): file_name
            for file_name in file_list
        }
    else:
        file_list = {
            (drive_file["title"], is_folder(drive_file)): drive_file
            for drive_file in file_list
        }

    regular_files, directories = [], []
    for (file_name, is_directory), file_obj in file_list.items():
        if is_directory:
            directories.append(file_obj)
        else:
            regular_files.append(file_obj)

    return regular_files, directories

def partition_file_lists(local_files, remote_files, local_directory):
    """
    Given two lists of files, one of local files and one of remote drive files, returns three lists:
    first, the files only in the first list and not in the second; second, files in both lists; third,
    files only in the second list and not in the first.
    """
    # Convert to list of (name, whether file is directory) pairs for easy comparison
    local_files = [
        (file_name, os.path.isdir(os.path.join(local_directory, file_name)))
        for file_name in local_files
    ]
    remote_files = {
        (drive_file["title"], is_folder(drive_file)): drive_file
        for drive_file in remote_files
    }

    local_set, remote_set = set(local_files), set(remote_files.keys())
    local_only, common, remote_only = set([]), set([]), set([])

    for t in local_files:
        if t not in remote_set:
            local_only.add(t)
        else:
            common.add(t)

    for t in remote_files.keys():
        if t not in local_set:
            remote_only.add(t)
        else:
            common.add(t)

    # Convert back to list of file names or list of drive file objects as needed
    local_only = [file_name for file_name, _ in local_only]
    common = [remote_files[t] for t in common]
    remote_only = [remote_files[t] for t in remote_only]

    return list(local_only), list(common), list(remote_only)

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
