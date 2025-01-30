"""A class to handle iRODS paths."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Iterable, Optional, Union

import irods
from irods.models import DataObject

import ibridges.icat_columns as icat
from ibridges.exception import (
    CollectionDoesNotExistError,
    DataObjectDoesNotExistError,
    DoesNotExistError,
    NotACollectionError,
    NotADataObjectError,
)
from ibridges.meta import MetaData


class IrodsPath:
    """A class analogous to the pathlib.Path for accessing iRods data.

    The IrodsPath can be used in much the same way as a Path from the pathlib library.
    Not all methods and attributes are implemented, and some methods/attributes behave
    subtly different from the pathlib implementation. They mostly do with the expansion
    of the home directory. With the IrodsPath, the '~' is used to denote the irods_home
    directory set in the Session object. So, for example the name of an irods path is
    always the name of the collection/subcollection, which is different from the pathlib
    behavior in some cases.
    """

    _current_working_path = ""

    def __init__(self, session, *args):
        """Initialize IrodsPath object similar to the Path object.

        It does take an extra argument in session.

        Parameters
        ----------
        session:
            Session that is used for the ipath.
        args:
            Specification of the path. For example: "x/z" or "x", "z".

        Raises
        ------
        TypeError:
            If the provided session does not have an 'irods_session' attribute.

        Examples
        --------
        >>> IrodsPath(session, "~")  # Get an iRods path of the irods_home collection.
        >>> IrodsPath(session, "/zone/home/some_collection")  # Absolute path.
        >>> IrodsPath(session, "some_collection")  # Relative path.
        >>> IrodsPath(session, "~/some_collection")  # Same as above.

        """
        self.session = session

        # Check if the session seems the right type.
        if not hasattr(session, "irods_session"):
            raise TypeError(f"{session} does not seem the right type: {type(session)}, should be "
                            "ibridges.session.Session.")

        # We don't want recursive IrodsPaths, so we take the
        # path outside of the IrodsPath object.
        args = [a._path if isinstance(a, IrodsPath) else a for a in args]
        self._path = PurePosixPath(*args)

        super().__init__()

    def absolute(self) -> IrodsPath:
        """Return the absolute path.

        This method does the expansion of the '~' and '.' symbols.

        Returns
        -------
            The absolute IrodsPath, without any '~' or '.'.

        Examples
        --------
        >>> IrodsPath(session, "~").absolute()
        IrodsPath(/, zone, user)

        """
        # absolute path
        if len(self._path.parts) == 0:
            return IrodsPath(self.session, self.session.home)
        if self._path.parts[0] == "~" or self._path.parts[0] == ".":
            begin, end = self.session.home, self._path.parts[1:]
        elif self._path.parts[0] == "/":
            begin, end = "/", self._path.parts[1:]
        else:
            begin, end = self.session.home, self._path.parts
        abs_str = str(PurePosixPath(begin, *end))
        return IrodsPath(self.session, abs_str)

    def __str__(self) -> str:
        """Get the absolute path if converting to string."""
        return str(self.absolute()._path)

    def __repr__(self) -> str:
        """Representation of the IrodsPath object in line with a Path object."""
        return f"IrodsPath({', '.join(self._path.parts)})"

    def __truediv__(self, other) -> IrodsPath:
        """Ensure that we can append just like the Path object."""
        return self.__class__(self.session, self._path, other)

    def __getattribute__(self, attr):
        """Make the IrodsPath transparent so that some Path functionality is available."""
        if attr in ["parts"]:
            return self._path.__getattribute__(attr)
        return super().__getattribute__(attr)

    def joinpath(self, *args) -> IrodsPath:
        """Concatenate another path to this one.

        Returns
        -------
            The concatenated path.

        Examples
        --------
        >>> IrodsPath(session, "~").joinpath("x", "y")
        IrodsPath(~, x, y)

        """
        return IrodsPath(self.session, self._path, *args)

    @property
    def parent(self) -> IrodsPath:
        """Return the parent directory of the current directory.

        Returns
        -------
            The parent just above the current directory

        Examples
        --------
        >>> IrodsPath(session, "/zone/home/user").parent
        IrodsPath("/", "zone", "home")
        >>> IrodsPath(session, "~").parent
        IrodsPath("/", "zone", "home")

        """
        return IrodsPath(self.session, self.absolute()._path.parent)  # pylint: disable=protected-access

    @property
    def name(self) -> str:
        """Return the name of the data object or collection.

        Returns
        -------
            The name of the object/collction, similarly to pathlib.


        Examples
        --------
        >>> IrodsPath(session, "/zone/home/user")
        "user"

        """
        return self.absolute().parts[-1]

    def remove(self):
        """Remove the data behind an iRODS path.

        Raises
        ------
        PermissionError:
            If the user has insufficient permission to remove the data.

        Examples
        --------
        >>> IrodsPath(session, "/home/zone/user/some_collection").remove()

        """
        try:
            if self.collection_exists():
                coll = self.session.irods_session.collections.get(str(self))
                coll.remove()
            elif self.dataobject_exists():
                obj = self.session.irods_session.data_objects.get(str(self))
                obj.unlink()
        except irods.exception.CUT_ACTION_PROCESSED_ERR as exc:
            raise PermissionError(f"While removing {self}: iRODS server forbids action.") from exc

    @staticmethod
    def create_collection(
        session, coll_path: Union[IrodsPath, str]
    ) -> irods.collection.iRODSCollection:
        """Create a collection and all parent collections that do not exist yet.

        Parameters
        ----------
        session:
            Session for which the collection is created.
        coll_path:
            Irods path to the collection to be created.

        Raises
        ------
        PermissionError:
            If the collection cannot be created due to insufficient permissions.

        Returns
        -------
        collection:
            The newly created collection.

        Examples
        --------
        >>> IrodsPath.create_collection(session, "/zone/home/user/some_collection")
        >>> IrodsPath.create_collection(session, IrodsPath(session, "~/some_collection"))

        """
        try:
            return session.irods_session.collections.create(str(coll_path))
        except irods.exception.CAT_NO_ACCESS_PERMISSION as error:
            raise PermissionError(f"Cannot create {str(coll_path)}, no access.") from error
        except irods.exception.CUT_ACTION_PROCESSED_ERR as exc:
            raise PermissionError(
                "While creating collection '{coll_path}': iRODS server forbids action."
            ) from exc

    def rename(self, new_name: Union[str, IrodsPath]) -> IrodsPath:
        """Change the name or the path of a data object or collection.

        New collections on the path will be created.

        Parameters
        ----------
        new_name: str or IrodsPath
            new name or a new full path


        Raises
        ------
        ValueError:
            If the new path already exists, or the path is in a different zone.
        PermissionError:
            If the new collection cannot be created.
        DoesNotExistError:
            If the path does not exist.

        Examples
        --------
        >>> IrodsPath(session, "~/some_collection").rename("~/new_collection")

        """
        if not self.exists():
            raise DoesNotExistError(f"{str(self)} does not exist.")

        # Build new path
        if str(new_name).startswith("/" + self.session.zone):
            new_path = IrodsPath(self.session, new_name)
        else:
            new_path = self.parent.joinpath(new_name)

        try:
            # Make sure new path exists on iRODS server
            if not new_path.parent.exists():
                self.create_collection(self.session, new_path.parent)

            if self.dataobject_exists():
                self.session.irods_session.data_objects.move(str(self), str(new_path))
            else:
                self.session.irods_session.collections.move(str(self), str(new_path))
            return new_path

        except irods.exception.SAME_SRC_DEST_PATHS_ERR as err:
            raise ValueError(f"Path {new_path} already exists.") from err
        except irods.exception.SYS_CROSS_ZONE_MV_NOT_SUPPORTED as err:
            raise ValueError(
                f"Path {new_path} needs to start with /{self.session.zone}/home"
            ) from err
        except irods.exception.CAT_NO_ACCESS_PERMISSION as err:
            raise PermissionError(f"Not allowed to move data to {new_path}") from err

    def collection_exists(self) -> bool:
        """Check if the path points to an iRODS collection.

        Examples
        --------
        >>> IrodsPath(session, "~/does_not_exist").collection_exists()
        False
        >>> IrodsPath(session, "~/some_dataobj").collection_exists()
        False
        >>> IrodsPath(session, "~/some_collection").collection_exists()
        True

        """
        return self.session.irods_session.collections.exists(str(self))

    def dataobject_exists(self) -> bool:
        """Check if the path points to an iRODS data object.

        Examples
        --------
        >>> IrodsPath(session, "~/does_not_exist").dataobject_exists()
        False
        >>> IrodsPath(session, "~/some_collection").dataobject_exists()
        False
        >>> IrodsPath(session, "~/some_dataobj").dataobject_exists()
        True

        """
        return self.session.irods_session.data_objects.exists(str(self))

    def exists(self) -> bool:
        """Check if the path already exists on the iRODS server.

        Examples
        --------
        >>> IrodsPath(session, "~/does_not_exist").exists()
        False
        >>> IrodsPath(session, "~/some_collection").exists()
        True
        >>> IrodsPath(session, "~/some_dataobj").exists()
        True

        """
        return self.dataobject_exists() or self.collection_exists()

    @property
    def collection(self) -> irods.collection.iRODSCollection:
        """Instantiate an iRODS collection.

        Raises
        ------
        NotADirectoryError:
            If the path points to a dataobject and not a collection.
        CollectionDoesNotExistError:
            If the path does not point to a dataobject or a collection.

        Returns
        -------
        iRODSCollection
            Instance of the collection with `path`.

        Examples
        --------
        >>> IrodsPath(session, "~/some_collection").collection
        <iRODSCollection 21260050 b'some_collection'>

        """
        if self.collection_exists():
            return self.session.irods_session.collections.get(str(self))
        if self.dataobject_exists():
            raise NotACollectionError(
                "Error retrieving collection, path is linked to a data object."
                " Use get_dataobject instead to retrieve the data object."
            )
        raise CollectionDoesNotExistError(str(self))

    @property
    def dataobject(self) -> irods.data_object.iRODSDataObject:
        """Instantiate an iRODS data object.

        Raises
        ------
        NotADataObjectError:
            If the path is pointing to a collection and not a data object.

        Returns
        -------
        iRODSDataObject
            Instance of the data object with `path`.

        Examples
        --------
        >>> IrodsPath(session, "~/some_dataobj.txt").dataobject
        <iRODSDataObject 24490075 some_dataobj.txt>

        """
        if self.dataobject_exists():
            return self.session.irods_session.data_objects.get(str(self))
        if self.collection_exists():
            raise NotADataObjectError(
                "Error retrieving data object, path is linked to a collection."
                " Use get_collection instead to retrieve the collection."
            )

        raise DataObjectDoesNotExistError(str(IrodsPath))

    def open(self, mode="r", **kwargs):
        """Open a data object for reading or writing.

        Parameters
        ----------
        mode, optional
            Whether to read or write, by default "r" meaning read. To write to
            a data object, use "w", appending to a data object can be done with "a".*
            Note that opening data objects is always done in binary
            mode, so to write a string you need to encode it, while reading a string from
            a data object requires you to decode it. You are advised to use a consistent
            (utf-8) encoding for all your data objects.
        kwargs:
            Extra keyword arguments for the python-irodsclient to parse.

        Returns
        -------
            A file handle to be used for reading or writing.

        Raises
        ------
        NotADataobjectError:
            When the IrodsPath points to a collection.
        DataObjectDoesNotExistError:
            When the data object does not exist and the read mode is given.

        Examples
        --------
        >>> ipath = Irodspath(session, "some_obj.txt")
        >>> with ipath.open("w") as handle:
        >>>     handle.write("This is a test string".encode("utf-8"))
        >>> with ipath.open("r") as handle:
        >>>     print(handle.read().decode("utf-8))
        This is a test string
        >>> with ipath.open("a") as handle:
        >>>     handle.write("A string appended at the end.".encode("utf-8"))

        """
        if self.collection_exists():
            raise NotADataObjectError("Cannot open collection, only data objects can be opened.")
        # Create the data object if it does not exist.
        if mode == "w" and not self.dataobject_exists():
            self.session.irods_session.data_objects.create(str(self))
        return self.dataobject.open(mode=mode, **kwargs)

    def walk(self, depth: Optional[int] = None) -> Iterable[IrodsPath]:
        """Walk on a collection.

        This iterates over all collections and data object for the path. If the
        path is pointing to a data object, it will simply yield this data object.

        Parameters
        ----------
        depth : int
            The maximum depth relative to the starting collection over which is walked.
            For example if depth equals 1, then it will iterate only over the subcollections
            and data objects directly under the starting collection.

        Returns
        -------
            Generator that generates all data objects and subcollections in the collection.

        Examples
        --------
        >>> for ipath in IrodsPath(session, "~").walk():
        >>>     print(ipath)
        IrodsPath(~, x)
        IrodsPath(~, x, y)
        IrodsPath(~, x, y, z.txt)
        >>> for ipath in IrodsPath(session, "~").walk(depth=1):
        >>>     print(ipath)
        IrodsPath(~, x)

        """
        all_data_objects: dict[str, list[IrodsPath]] = defaultdict(list)
        prc_data_objects = _get_data_objects(self.session, self.collection, depth=depth)
        for path, name, size, checksum in prc_data_objects:
            abs_path = IrodsPath(self.session, path).absolute()
            ipath = CachedIrodsPath(self.session, size, True, checksum, path, name)
            all_data_objects[str(abs_path)].append(ipath)
        all_collections = _get_subcoll_paths(self.session, self.collection, depth=depth)
        all_collections = sorted(all_collections, key=str)
        sub_collections: dict[str, list[IrodsPath]] = defaultdict(list)
        for cur_col in all_collections:
            sub_collections[str(cur_col.parent)].append(cur_col)
        yield from _recursive_walk(self, sub_collections, all_data_objects, self, 0, depth)

    def relative_to(self, other: IrodsPath) -> PurePosixPath:
        """Calculate the relative path compared to our path.

        Can only calculate the relateive path compared to another irods path.

        >>> IrodsPath(session, "~/col/dataobj.txt").relative_to(IrodsPath(session, "~"))
        PurePosixPath(col, dataobj.txt)
        >>> IrodsPath(session, "~/col/dataobj.txt").relative_to(IrodsPath(session, "~/col"))
        PurePosixPath(dataobj.txt)
        """
        return PurePosixPath(str(self.absolute())).relative_to(PurePosixPath(str(other.absolute())))

    @property
    def size(self) -> int:
        """Collect the sizes of a data object or a collection.

        Returns
        -------
        int :
            Total size [bytes] of the iRODS object or all iRODS objects in the collection.

        Raises
        ------
        FileNotFoundError:
            If the path is neither a collection or data object.

        Examples
        --------
        >>> IrodsPath(session, "~/some_collection").size
        12345
        >>> IrodsPath(session, "~/some_dataobj.txt").size
        623

        """
        if not self.exists():
            raise FileNotFoundError(
                f"Path '{str(self)}' does not exist;"
                " it is neither a collection nor a dataobject."
            )
        if self.dataobject_exists():
            return self.dataobject.size
        all_objs = _get_data_objects(self.session, self.collection)
        return sum(size for _, _, size, _ in all_objs)

    @property
    def checksum(self) -> str:
        """Checksum of the data object.

        If not calculated yet, it will be computed on the server.

        Returns
        -------
            The checksum of the data object.

        Raises
        ------
        DoesNotExistError:
            When the path does not exist.
        NotADataObjectError:
            When the path points to a collection.

        Examples
        --------
        >>> IrodsPath(session, "~/some_dataobj.txt").checksum
        'sha2:XGiECYZOtUfP9lnCGyZaBBkBGLaJJw1p6eoc0GxLeKU='

        """
        if self.dataobject_exists():
            dataobj = self.dataobject
            return dataobj.checksum if dataobj.checksum is not None else dataobj.chksum()
        if self.collection_exists():
            raise NotADataObjectError("Cannot take checksum of a collection.")
        raise DoesNotExistError(
            f"Cannot take checksum of {str(self)} irods path which does not exist.")

    @property
    def meta(self) -> MetaData:
        """Metadata linked to the dataobject or collection.

        Returns
        -------
            The Metadata object pertaining to the dataobject or collection.

        Raises
        ------
        DoesNotExistError:
            When the path does not point to a data object or collection.

        """
        if self.dataobject_exists():
            return MetaData(self.dataobject)
        if self.collection_exists():
            return MetaData(self.collection)
        raise DoesNotExistError(
            "Cannot get metadata for path that is neither dataobject or collection:"
            f" {self}")



def _recursive_walk(cur_col: IrodsPath, sub_collections: dict[str, list[IrodsPath]],
                    all_dataobjects: dict[str, list[IrodsPath]], start_col: IrodsPath,
                    depth: int, max_depth: Optional[int]):
    yield cur_col
    if max_depth is not None and depth >= max_depth:
        return
    for sub_col in sub_collections[str(cur_col)]:
        yield from _recursive_walk(
            sub_col, sub_collections, all_dataobjects, start_col, depth + 1, max_depth
        )
    yield from sorted(all_dataobjects[str(cur_col)], key=str)


class CachedIrodsPath(IrodsPath):
    """Cached version of the IrodsPath.

    This version should generally not be used by users, but is used for performance reasons.
    It will cache the size checksum and whether it is a data object. This can be invalidated
    when other ibridges operations are used.
    """

    def __init__(
        self, session, size: Optional[int], is_dataobj: bool, checksum: Optional[str], *args
    ):
        """Initialize CachedIrodsPath.

        Parameters
        ----------
        session:
            Session used for the IrodsPath
        size:
            Size of the dataobject, None for collections.
        is_dataobj:
            Whether the path points to a data object.`
        checksum:
            The checksum of the dataobject, None for collections.
        args:
            Remainder of the path

        """
        self._is_dataobj = is_dataobj
        self._size = size
        self._checksum = checksum
        super().__init__(session, *args)

    @property
    def size(self) -> int:
        """See IrodsPath."""
        if self._size is None:
            return super().size
        return self._size

    @property
    def checksum(self) -> str:
        """See IrodsPath."""
        if self._checksum is None:
            return super().checksum
        return self._checksum

    def __repr__(self) -> str:
        """Representation of the CachedIrodsPath object in line with a Path object."""
        return f"CachedIrodsPath({', '.join(self._path.parts)})"

    def dataobject_exists(self) -> bool:
        """See IrodsPath."""
        return self._is_dataobj

    def collection_exists(self) -> bool:
        """See IrodsPath."""
        return not self._is_dataobj


def _get_data_objects(
    session, coll: irods.collection.iRODSCollection,
    depth: Optional[int] = None,
) -> list[tuple[str, str, int, str]]:
    """Retrieve all data objects in a collection and all its subcollections.

    Parameters
    ----------
    session:
        Session to get the data objects with.
    coll : irods.collection.iRODSCollection
        The collection to search for all data objects
    depth:
        Depth of the data object search, only used for depth==1.

    Returns
    -------
    list of all data objects
        [(collection path, name, size, checksum)]

    """
    # all objects in the collection
    objs = [(obj.collection.path, obj.name, obj.size, obj.checksum) for obj in coll.data_objects]
    if depth == 1:
        return objs

    # all objects in subcollections
    data_query = session.irods_session.query(
        icat.COLL_NAME, icat.DATA_NAME, DataObject.size, DataObject.checksum
    )
    data_query = data_query.filter(icat.LIKE(icat.COLL_NAME, coll.path + "/%"))
    for res in data_query.get_results():
        path, name, size, checksum = res.values()
        objs.append((path, name, size, checksum))

    return objs


def _get_subcoll_paths(session, coll: irods.collection.iRODSCollection,
                       depth: Optional[int] = None) -> list:
    """Retrieve all sub collections in a sub tree starting at coll and returns their IrodsPaths."""
    if depth == 1:
        return [CachedIrodsPath(session, None, False, None, subcol.path)
                for subcol in coll.subcollections]

    coll_query = session.irods_session.query(icat.COLL_NAME)
    coll_query = coll_query.filter(icat.LIKE(icat.COLL_NAME, coll.path + "/%"))

    return [CachedIrodsPath(session, None, False, None, p) for r in coll_query.get_results()
            for p in r.values()] + [CachedIrodsPath(session, None, False, None, coll.path)]
