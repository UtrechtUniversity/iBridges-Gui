"""Data and metadata transfers.

Transfer data between local file system and iRODS, includes upload, download and sync.
Also includes operations for creating a local metadata archive and using this archive
to set the metadata.
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Optional, Union

import irods.collection
import irods.data_object
import irods.exception

from ibridges.exception import (
    CollectionDoesNotExistError,
    DataObjectExistsError,
    DoesNotExistError,
    NotACollectionError,
)
from ibridges.executor import Operations
from ibridges.path import CachedIrodsPath, IrodsPath
from ibridges.session import Session
from ibridges.util import checksums_equal

NUM_THREADS = 4


def upload(
    session: Session,
    local_path: Union[str, Path],
    irods_path: Union[str, IrodsPath],
    overwrite: bool = False,
    ignore_err: bool = False,
    resc_name: str = "",
    copy_empty_folders: bool = True,
    options: Optional[dict] = None,
    dry_run: bool = False,
    metadata: Union[None, str, Path] = None,
    **kwargs
) -> Operations:
    """Upload a local directory or file to iRODS.

    Parameters
    ----------
    session:
        Session to upload the data to.
    local_path:
        Absolute path to the directory to upload
    irods_path:
        Absolute irods destination path
    overwrite:
        If data object or collection already exists on iRODS, overwrite
    ignore_err:
        If an error occurs during upload, and ignore_err is set to True, any errors encountered
        will be transformed into warnings and iBridges will continue to upload the remaining files.
        By default all errors will stop the process of uploading.
    resc_name:
        Name of the resource to which data is uploaded, by default the server will decide
    copy_empty_folders:
        Create respective iRODS collection for empty folders. Default: True.
    options:
        More options for the upload
    dry_run:
        Whether to do a dry run before uploading the files/folders.
    metadata:
        If not None, it should point to a file that contains the metadata for the upload.
    kwargs:
        Extra arguments for executing the upload operation, e.g. progress_bar = False.

    Returns
    -------
        Operations object that can be used to execute the upload in case of a dry-run.

    Raises
    ------
    FileNotFoundError:
        If the local_path is not a valid filename of directory.
    DataObjectExistsError:
        If the data object to be uploaded already exists without using overwrite==True.
    PermissionError:
        If the iRODS server does not allow the collection or data object to be created.

    Examples
    --------
    >>> ipath = IrodsPath(session, "~/some_col")
    >>> # Below will create a collection with "~/some_col/dir".
    >>> upload(session, Path("dir"), ipath)

    >>> # Same, but now data objects that exist will be overwritten.
    >>> upload(session, Path("dir"), ipath, overwrite=True)

    >>> # Perform the upload in two steps with a dry-run
    >>> ops = upload(session, Path("some_file.txt"), ipath, dry_run=True)  # Does not upload
    >>> ops.print_summary()  # Check if this is what you want here.
    >>> ops.execute()  # Performs the upload

    """
    local_path = Path(local_path)
    ipath = IrodsPath(session, irods_path)
    ops = Operations()
    if local_path.is_dir():
        idest_path = ipath / local_path.name
        if not overwrite and idest_path.dataobject_exists():
            raise DataObjectExistsError(f"Data object {idest_path} already exists.")
        ops = _up_sync_operations(
            local_path, idest_path, copy_empty_folders=copy_empty_folders, depth=None,
            overwrite=overwrite, ignore_err=ignore_err
        )
        if not idest_path.collection_exists():
            ops.add_create_coll(idest_path)
        if not ipath.collection_exists():
            ops.add_create_coll(ipath)
    elif local_path.is_file():
        idest_path = ipath / local_path.name if ipath.collection_exists() else ipath
        obj_exists = idest_path.dataobject_exists()
        if not obj_exists or _transfer_needed(idest_path, local_path, overwrite, ignore_err):
            ops.add_upload(local_path, idest_path)

    elif local_path.is_symlink():
        raise FileNotFoundError(
            f"Cannot upload symbolic link {local_path}, please supply a direct path."
        )
    else:
        raise FileNotFoundError(f"Cannot upload {local_path}: file or directory does not exist.")
    ops.resc_name = resc_name
    ops.options = options
    if metadata is not None:
        ops.add_meta_upload(idest_path, metadata)
    if not dry_run:
        ops.execute(session, ignore_err=ignore_err, **kwargs)
    return ops


def download(
    session: Session,
    irods_path: Union[str, IrodsPath],
    local_path: Union[str, Path],
    overwrite: bool = False,
    ignore_err: bool = False,
    resc_name: str = "",
    copy_empty_folders: bool = True,
    options: Optional[dict] = None,
    dry_run: bool = False,
    metadata: Union[None, str, Path] = None,
    **kwargs
) -> Operations:
    """Download a collection or data object to the local filesystem.

    Parameters
    ----------
    session:
        Session to download the collection from.
    irods_path:
        Absolute irods source path pointing to a collection
    local_path:
        Absolute path to the destination directory
    overwrite:
        If an error occurs during download, and ignore_err is set to True, any errors encountered
        will be transformed into warnings and iBridges will continue to download the remaining
        files.
        By default all errors will stop the process of downloading.
    ignore_err:
        Collections: If download of an item fails print error and continue with next item.
    resc_name:
        Name of the resource from which data is downloaded, by default the server will decide.
    copy_empty_folders:
        Create respective local directory for empty collections.
    options:
        More options for the download
    dry_run:
        Whether to do a dry run before uploading the files/folders.
    metadata:
        If not None, the path to store the metadata to in JSON format.
        It is recommended to use the .json suffix.
    kwargs:
        Extra arguments for executing the download operation, e.g. progress_bar = False.

    Returns
    -------
        Operations object that can be used to execute the download in case of a dry-run.

    Raises
    ------
    PermissionError:
        If the iRODS server (for whatever reason) forbids downloading the file or
        (part of the) collection.
    DoesNotExistError:
        If the irods_path is not pointing to either a collection or a data object.
    FileExistsError:
        If the irods_path points to a data object and the local file already exists.
    NotADirectoryError:
        If the irods_path is a collection, while the destination is a file.

    Examples
    --------
    >>> # Below will create a directory "some_local_dir/some_collection"
    >>> download(session, "~/some_collection", "some_local_dir")

    >>> # Below will create a file "some_local_dir/some_obj.txt"
    >>> download(session, IrodsPath(session, "some_obj.txt"), "some_local_dir")

    >>> # Below will create a file "new_file.txt" in two steps.
    >>> ops = download(session, "~/some_obj.txt", "new_file.txt", dry_run=True)
    >>> ops.execute()

    """
    irods_path = IrodsPath(session, irods_path)
    local_path = Path(local_path)

    if irods_path.collection_exists():
        if local_path.is_file():
            raise NotADirectoryError(
                f"Cannot download to directory {local_path} "
                "since a file with the same name exists."
            )

        ops = _down_sync_operations(
            irods_path, local_path / irods_path.name, metadata=metadata,
            copy_empty_folders=copy_empty_folders, overwrite=overwrite,
            ignore_err=ignore_err
        )
        if not local_path.is_dir():
            ops.add_create_dir(Path(local_path))
    elif irods_path.dataobject_exists():
        ops = Operations()

        if local_path.is_dir():
            local_path = local_path / irods_path.name
        if not local_path.is_file() or _transfer_needed(
                irods_path, local_path, overwrite, ignore_err):
            ops.add_download(irods_path, local_path)
        if metadata is not None:
            ops.add_meta_download(irods_path, irods_path, metadata)

    else:
        raise DoesNotExistError(f"Data object or collection not found: '{irods_path}'")

    ops.resc_name = resc_name
    ops.options = options
    if not dry_run:
        ops.execute(session, ignore_err=ignore_err, **kwargs)
    return ops


def create_collection(
    session: Session, coll_path: Union[IrodsPath, str]
) -> irods.collection.iRODSCollection:
    """Create a collection and all parent collections that do not exist yet.

    Alias for :meth:`ibridges.path.IrodsPath.create_collection`

    Parameters
    ----------
    session:
        Session to create the collection for.
    coll_path: IrodsPath
        Collection path

    Raises
    ------
    PermissionError:
        If creating a collection is not allowed by the server.


    Examples
    --------
    >>> create_collection(session, IrodsPath("~/new_collection"))

    """
    return IrodsPath.create_collection(session, coll_path)


def sync(
    session: Session,
    source: Union[str, Path, IrodsPath],
    target: Union[str, Path, IrodsPath],
    max_level: Optional[int] = None,
    dry_run: bool = False,
    ignore_err: bool = False,
    copy_empty_folders: bool = False,
    resc_name: str = "",
    options: Optional[dict] = None,
    metadata: Union[None, str, Path] = None,
    **kwargs
) -> Operations:
    """Synchronize data between local and remote copies.

    The command can be in one of the two modes: synchronization of data from the client's local file
    system to iRODS, or from iRODS to the local file system. The mode is determined by the type of
    the values for `source` and `target`: objects with type :class:`ibridges.path.IrodsPath`  will
    be interpreted as remote paths, while types :code:`str` and :code:`Path` with be interpreted
    as local paths.

    Files/data objects that have the same checksum will not be synchronized.


    Parameters
    ----------
    session:
        An authorized iBridges session.
    source:
        Existing local folder or iRODS collection. An exception will be raised if it doesn't exist.
    target:
        Existing local folder or iRODS collection. An exception will be raised if it doesn't exist.
    max_level:
        Controls the depth up to which the file tree will be synchronized. A max level of 1
        synchronizes only the source's root, max level 2 also includes the first set of
        subfolders/subcollections and their contents, etc. Set to None, there is no limit
        (full recursive synchronization).
    dry_run:
        List all source files and folders that need to be synchronized without actually
        performing synchronization.
    ignore_err:
        If an error occurs during the transfer, and ignore_err is set to True,
        any errors encountered will be transformed into warnings and iBridges will continue
        to transfer the remaining files.
    copy_empty_folders:
        Controls whether folders/collections that contain no files or subfolders/subcollections
        will be synchronized.
    resc_name:
        Name of the resource from which data is downloaded, by default the server will decide.
    options:
        More options for the download/upload
    metadata:
        If not None, the location to get the metadata from or store it to.
    kwargs:
        Extra arguments for executing the sync operation, e.g. progress_bar = False.

    Raises
    ------
    CollectionDoesNotExistError:
        If the source collection does not exist
    NotACollectionError:
        If the source is a data object.
    NotADirectoryError:
        If the local source is not a directory.

    Returns
    -------
        An operations object to execute the sync if dry-run is True.

    Examples
    --------
    >>> # Below, all files/dirs in "some_local_dir" will be transferred into "some_remote_coll"
    >>> sync(session, "some_local_dir", IrodsPath(session, "~/some_remote_col")

    >>> # Below, all data objects/collections in "col" will tbe transferred into "some_local_dir"
    >>> sync(session, IrodsPath(session, "~/col"), "some_local_dir")

    """
    _param_checks(source, target)

    if isinstance(source, IrodsPath):
        if not source.collection_exists():
            if source.dataobject_exists():
                raise NotACollectionError(f"Source '{source.absolute()}' is a data object, "
                                     "can only sync collections.")
            raise CollectionDoesNotExistError(
                f"Source collection '{source.absolute()}' does not exist")
    else:
        if not Path(source).is_dir():
            raise NotADirectoryError(f"Source folder '{source}' is not a directory or "
                                     "does not exist.")

    if isinstance(source, IrodsPath):
        ops = _down_sync_operations(
            source, Path(target), copy_empty_folders=copy_empty_folders, depth=max_level,
            metadata=metadata, overwrite=True
        )
    else:
        ops = _up_sync_operations(
            Path(source), IrodsPath(session, target), copy_empty_folders=copy_empty_folders,
            depth=max_level, overwrite=True)
        if metadata is not None:
            ops.add_meta_upload(target, metadata)  # type: ignore

    ops.resc_name = resc_name
    ops.options = options
    if not dry_run:
        ops.execute(session, ignore_err=ignore_err, **kwargs)

    return ops


def create_meta_archive(session: Session, source: Union[str, IrodsPath],
                        meta_fp: Union[str, Path], dry_run: bool = False):
    """Create a local archive file for the metadata.

    The archive is a utf-8 encoded JSON file with the metadata of all subcollections
    and data objects. To re-use this archive use the function :func:`apply_meta_archive`.

    Parameters
    ----------
    session
        Session with the iRODS server.
    source
        Source iRODS path to create the archive for. This should be a collection.
    meta_fp
        Metadata archive file.
    dry_run, optional
        Whether to do a dry run. If so, the archive itself won't be created, by default False.

    Returns
    -------
        The Operations object that allows the user to execute the operations using
        ops.execute(session).

    Raises
    ------
    CollectionDoesNotExistError:
        If the source collection does not exist.
    NotACollectionError:
        If the source is not a collection but a data object.

    Examples
    --------
    >>> create_meta_archive(session, "/some/home/collection", "meta_archive.json")

    """
    root_ipath = IrodsPath(session, source)
    if not root_ipath.collection_exists():
        if root_ipath.dataobject_exists():
            raise NotACollectionError("Cannot download metadata archive: "
                                 f"'{root_ipath}' is a data object, need a collection.")
        raise CollectionDoesNotExistError("Cannot download metadata archive: "
                                    f"'{root_ipath}' does not exist.")
    operations = Operations()
    for ipath in root_ipath.walk():
        operations.add_meta_download(root_ipath, ipath, meta_fp)
    if not dry_run:
        operations.execute(session)
    return operations


def apply_meta_archive(session, meta_fp: Union[str, Path], ipath: Union[str, IrodsPath],
                       dry_run: bool = False):
    """Apply a metadata archive to set the metadata of collections and data objects.

    The archive is a utf-8 encoded JSON file with the metadata of all subcollections
    and data objects. The archive can be created with the function :func:`create_meta_archive`.

    Parameters
    ----------
    session
        Session with the iRODS server.
    meta_fp
        Metadata archive file to use to set the metadata.
    ipath
        Root collection to set the metadata for. The collections and data objects relative to this
        root collection should be the same as the ones in the metadata archive.
    dry_run, optional
        If True, only create an operations object, but do not execute the operation, default False.

    Returns
    -------
        The Operations object that allows the user to execute the operations using
        ops.execute(session).

    Raises
    ------
    CollectionDoesNotExistError:
        If the ipath does not exist.
    NotACollectionError:
        If the ipath is not a collection.

    Examples
    --------
    >>> apply_meta_archive(session, "meta_archive.json", "/some/home/collection")

    """
    ipath = IrodsPath(session, ipath)
    if not ipath.collection_exists():
        if ipath.dataobject_exists():
            raise NotACollectionError(f"Cannot apply metadata archive, since '{ipath}' "
                                     "is a data object and not a collection.")
        raise CollectionDoesNotExistError(
            f"Cannot apply metadata archive, '{ipath}' does not exist.")
    operations = Operations()
    operations.add_meta_upload(ipath, meta_fp)
    if not dry_run:
        operations.execute(session)
    return operations


def _param_checks(source, target):
    if not isinstance(source, IrodsPath) and not isinstance(target, IrodsPath):
        raise TypeError("Either source or target should be an iRODS path.")

    if isinstance(source, IrodsPath) and isinstance(target, IrodsPath):
        raise TypeError("iRODS to iRODS copying is not supported.")


def _transfer_needed(source, dest, overwrite, ignore_err):
    if isinstance(source, IrodsPath):
        ipath = source
        lpath = dest
    else:
        ipath = dest
        lpath = source

    if not overwrite:
        if not ignore_err:
            err_msg = (f"Cannot overwrite {source} -> {dest} unless overwrite==True. "
                       f"To ignore this error and skip the files use ignore_err==True.")
            if isinstance(dest, IrodsPath):
                raise DataObjectExistsError(err_msg)
            else:
                raise FileExistsError(err_msg)
        warnings.warn(f"Skipping file/data object {source} -> {dest} since "
                      f"both exist and overwrite == False.")
        return False
    if checksums_equal(ipath, lpath):
        return False
    return True


def _down_sync_operations(isource_path: IrodsPath, ldest_path: Path,
                          overwrite: bool,
                          ignore_err: bool = False,
                          copy_empty_folders: bool  =True, depth: Optional[int] = None,
                          metadata: Union[None, str, Path] = None) -> Operations:
    operations = Operations()
    for ipath in isource_path.walk(depth=depth):
        if metadata is not None:
            operations.add_meta_download(isource_path, ipath, metadata)
        lpath = ldest_path.joinpath(*ipath.relative_to(isource_path).parts)
        if ipath.dataobject_exists():
            if lpath.is_file():
                if _transfer_needed(ipath, lpath, overwrite, ignore_err):
                    operations.add_download(ipath, lpath)
            else:
                operations.add_download(ipath, lpath)
            if not lpath.parent.exists():
                operations.add_create_dir(lpath.parent)
        elif ipath.collection_exists() and copy_empty_folders:
            if not lpath.exists():
                operations.add_create_dir(lpath)
    return operations


def _up_sync_operations(lsource_path: Path, idest_path: IrodsPath,  # pylint: disable=too-many-branches
                        overwrite: bool,
                        copy_empty_folders: bool = True, depth: Optional[int] = None,
                        ignore_err: bool = False) -> Operations:
    operations = Operations()
    session = idest_path.session
    try:
        remote_ipaths = {str(ipath): ipath for ipath in idest_path.walk()}
    except irods.exception.CollectionDoesNotExist:
        remote_ipaths = {}
    for root, folders, files in os.walk(lsource_path):
        root_part = Path(root).relative_to(lsource_path)
        if depth is not None and len(root_part.parts) > depth:
            continue
        root_ipath = idest_path.joinpath(*root_part.parts)
        for cur_file in files:
            ipath = root_ipath / cur_file
            lpath = lsource_path / root_part / cur_file

            # Ignore symlinks
            if lpath.is_symlink():
                warnings.warn(f"Ignoring symlink {lpath}.")
                continue
            if str(ipath) in remote_ipaths:
                ipath = remote_ipaths[str(ipath)]
                if _transfer_needed(ipath, lpath, overwrite, ignore_err):
                    operations.add_upload(lpath, ipath)
            else:
                ipath = CachedIrodsPath(session, None, False, None, str(ipath))
                operations.add_upload(lpath, ipath)
        if copy_empty_folders:
            for fold in folders:
                # Ignore folder symlinks
                lpath = lsource_path / root_part / fold
                if lpath.is_symlink():
                    warnings.warn(f"Ignoring symlink {lpath}.")
                    continue
                if str(root_ipath / fold) not in remote_ipaths:
                    operations.add_create_coll(root_ipath / fold)
        if str(root_ipath) not in remote_ipaths:
            operations.add_create_coll(root_ipath)
    return operations
