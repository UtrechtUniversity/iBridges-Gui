"""iBridges exceptions dealing with missing paths."""

from irods.exception import CollectionDoesNotExist as CollectionDoesNotExistError
from irods.exception import DataObjectDoesNotExist as DataObjectDoesNotExistError
from irods.exception import DoesNotExist as DoesNotExistError

__all__ = ["CollectionDoesNotExistError", "DataObjectDoesNotExistError"]


class NotACollectionError(DoesNotExistError):
    """When the path is not a collection."""


class NotADataObjectError(DoesNotExistError):
    """When the path is not a data object."""

class DataObjectExistsError(DoesNotExistError):
    """When the data object already exists."""
