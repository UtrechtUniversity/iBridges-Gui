"""Operations to directly manipulate metadata on the iRODS server."""

from __future__ import annotations

import re
import warnings
from typing import Any, Iterator, Optional, Sequence, Union

import irods
import irods.exception
import irods.meta


class MetaData:
    """iRODS metadata operations.

    This allows for adding and deleting of metadata entries for data objects
    and collections.

    Parameters
    ----------
    item:
        The data object or collection to attach the metadata object to.
    blacklist:
        A regular expression for metadata names/keys that should be ignored.
        By default all metadata starting with `org_` is ignored.


    Examples
    --------
    >>> meta = MetaData(coll)
    >>> "Author" in meta
    True
    >>> for entry in meta:
    >>>     print(entry.key, entry.value, entry.units)
    Author Ben
    Mass 10 kg
    >>> len(meta)
    2
    >>> meta.add("Author", "Emma")
    >>> meta.set("Author", "Alice")
    >>> meta.update("Author", "Alice", mew_value="Bob")
    >>> meta.delete("Author")
    >>> print(meta)
    {Mass, 10, kg}

    """

    def __init__(
        self,
        item: Union[irods.data_object.iRODSDataObject, irods.collection.iRODSCollection],
        blacklist: str = r"^org_*",
    ):
        """Initialize the metadata object."""
        self.item = item
        self.blacklist = blacklist

    def __iter__(self) -> Iterator:
        """Iterate over all metadata key/value/units triplets."""
        if self.blacklist is None:
            yield self.item.metadata.items()
        for meta in self.item.metadata.items():
            if self.blacklist is None:
                yield meta
            elif re.match(self.blacklist, meta.name) is None:
                yield meta
            else:
                warnings.warn(f"Ignoring metadata entry with value {meta.name}, because it matches "
                              f"the blacklist {self.blacklist}.")

    def __len__(self) -> int:
        """Get the number of non-blacklisted metadata entries."""
        return len([x for x in self])  # pylint: disable=unnecessary-comprehension

    def __contains__(self, val: Union[str, Sequence]) -> bool:
        """Check whether a key, key/val, key/val/units pairs are in the metadata.

        Returns
        -------
            True if key/val/unit pairs are present in the item.

        Examples
        --------
        >>> "Author" in meta
        True
        >>> ("Author", "Ben") in meta
        False
        >>> ("Release", "2000", "year") in meta
        True

        """
        if isinstance(val, str):
            val = [val]
        all_attrs = ["name", "value", "units"][: len(val)]
        for meta in self:
            n_same = 0
            for i_attr, attr in enumerate(all_attrs):
                if getattr(meta, attr) == val[i_attr] or val[i_attr] is None:
                    n_same += 1
                else:
                    break
            if n_same == len(val):
                return True
        return False

    def __repr__(self) -> str:
        """Create a sorted representation of the metadata."""
        return f"MetaData<{self.item.path}>"

    def __str__(self) -> str:
        """Return a string showing all metadata entries."""
        # Sort the list of items name -> value -> units, where None is the lowest
        meta_list = list(self)
        meta_list = sorted(meta_list, key=lambda m: (m.units is None, m.units))
        meta_list = sorted(meta_list, key=lambda m: (m.value is None, m.value))
        meta_list = sorted(meta_list, key=lambda m: (m.name is None, m.name))
        return "\n".join(f" - {{name: {meta.name}, value: {meta.value}, units: {meta.units}}}"
                         for meta in meta_list)

    def add(self, key: str, value: str, units: Optional[str] = None):
        """Add metadata to an item.

        This will never overwrite an existing entry. If the triplet already exists
        it will throw an error instead. Note that entries are only considered the same
        if all of the key, value and units are the same. Alternatively you can use the
        :meth:`set` method to remove all entries with the same key, before adding the
        new entry.

        Parameters
        ----------
        key:
            Key of the new entry to add to the item.
        value:
            Value of the new entry to add to the item.
        units:
            The units of the new entry.

        Raises
        ------
        ValueError:
            If the metadata already exists.
        PermissionError:
            If the metadata cannot be updated because the user does not have sufficient permissions.

        Examples
        --------
        >>> meta.add("Author", "Ben")
        >>> meta.add("Mass", "10", "kg")

        """
        try:
            if (key, value, units) in self:
                raise ValueError("ADD META: Metadata already present")
            if re.match(self.blacklist, key):
                raise ValueError(
                        f"ADD META: Key must not start with {self.blacklist}.")
            self.item.metadata.add(key, value, units)
        except irods.exception.CAT_NO_ACCESS_PERMISSION as error:
            raise PermissionError("UPDATE META: no permissions") from error

    def set(self, key: str, value: str, units: Optional[str] = None):
        """Set the metadata entry.

        If the metadata entry already exists, then all metadata entries with
        the same key will be deleted before adding the new entry. An alternative
        is using the :meth:`add` method to only add to the metadata entries and not
        delete them.

        Parameters
        ----------
        key:
            Key of the new entry to add to the item.
        value:
            Value of the new entry to add to the item.
        units:
            The units of the new entry.

        Raises
        ------
        PermissionError:
            If the user does not have sufficient permissions to set the metadata.

        Examples
        --------
        >>> meta.set("Author", "Ben")
        >>> meta.set("mass", "10", "kg")

        """
        self.delete(key)
        self.add(key, value, units)

    def update(self, key: str, value: str, units: Optional[str] = None,
               new_value: Optional[str] = None, new_units: Optional[str] = None):
        """Update the value or the units of a metadata entry.

        Parameters
        ----------
        key:
            Key of the entry.
        value:
            Value of the entry.
        units:
            The units of the entry.
        new_value:
            The value to replace the existing value with.
        new_units:
            The units to replace the existing units with. To delete the unit use ''.

        Raises
        ------
        PermissionError:
            If the user does not have sufficient permissions to set the metadata.
        ValueError:
            The metadata item to change does not exist or
            The new metadata is already present or
            The new value and the new unit are None or
            The new value is the empty string.

        Examples
        --------
        >>> meta.update("Author", "Ben", new_value = "Alice")
        >>> meta.update("mass", "10", "kg", new_units = "g")

        """
        if new_value is None and new_units is None:
            raise ValueError("No new value or new unit set.")
        if new_value == '':
            raise ValueError("New value cannot be empty.")
        if units is None:
            if (key, value) not in self:
                raise ValueError(f"{key}, {value} does not exist.")
        else:
            if (key, value, units) not in self:
                raise ValueError(f"{key}, {value} {units} does not exist.")

        # Check for None, allow '' for new_units
        if new_value is not None and new_units is not None:
            self.add(key, new_value, new_units)
        elif new_value is not None:
            self.add(key, new_value, units)
        elif new_units is not None:
            self.add(key, value, new_units)

        if units:
            self.delete(key, value, units)
        else:
            self.delete(key, value, '')

    def delete(self, key: str, value: Union[None, str] = ...,  # type: ignore
               units: Union[None, str] = ...):  # type: ignore
        """Delete a metadata entry of an item.

        Parameters
        ----------
        key:
            Key of the entry to remove.
        value:
            Value of the  entry to remove. If the Ellipsis value [...] is used,
            then all entries with this value will be deleted.
        units:
            The units of the entry to remove. If the Elipsis value [...] is used, then all entries
            with any units will be deleted (but still constrained to the supplied keys and values).

        Raises
        ------
        KeyError:
            If the to be deleted key cannot be found.
        PermissionError:
            If the user has insufficient permissions to delete the metadata.

        Examples
        --------
        >>> # Delete the metadata entry with mass 10 kg
        >>> meta.delete("mass", "10", "kg")
        >>> # Delete all metadata with key mass  and value 10
        >>> meta.delete("mass", "10")
        >>> # Delete all metadata with the key mass
        >>> meta.delete("mass")

        """
        try:
            if value is ... or units is ...:
                all_metas = self.item.metadata.get_all(key)
                for meta in all_metas:
                    if value is ... or value == meta.value and units is ... or units == meta.units:
                        self.item.metadata.remove(meta)
            else:
                self.item.metadata.remove(key, value, units)
        except irods.exception.CAT_SUCCESS_BUT_WITH_NO_INFO as error:
            raise KeyError(
                f"Cannot delete metadata with key '{key}', value '{value}'"
                f" and units '{units}' since it does not exist."
            ) from error
        except irods.exception.CAT_NO_ACCESS_PERMISSION as error:
            raise ValueError(
                f"Cannot delete metadata due to insufficient permission "
                f"for path '{self.item.path}'."
            ) from error

    def clear(self):
        """Delete all metadata entries belonging to the item.

        Only entries that are on the blacklist are not deleted.

        Examples
        --------
        >>> meta.add("Ben", "10", "kg")
        >>> print(meta)
        - {name: Ben, value: 10, units: kg}
        >>> metadata.clear()
        >>> print(len(meta))  # empty
        0

        Raises
        ------
        PermissionError:
            If the user has insufficient permissions to delete the metadata.

        """
        for meta in self:
            self.item.metadata.remove(meta)

    def to_dict(self, keys: Optional[list] = None) -> dict:
        """Convert iRODS metadata (AVUs) and system information to a python dictionary.

        This dictionary can later be used to restore the metadata to an iRODS object with
        the :meth:`from_dict` method.

        Examples
        --------
        >>> meta.to_dict()
        {
            "name": item.name,
            "irods_id": item.id, #iCAT database ID
            "checksum": item.checksum if the item is a data object
            "metadata": [(m.name, m.value, m.units)]
        }

        Parameters
        ----------
        keys:
            List of Attribute names which should be exported to "metadata".
            By default all will be exported.

        Returns
        -------
            Dictionary containing the metadata.

        """
        meta_dict: dict[str, Any] = {}
        meta_dict["name"] = self.item.name
        meta_dict["irods_id"] = self.item.id
        if isinstance(self.item, irods.data_object.iRODSDataObject):
            meta_dict["checksum"] = self.item.checksum
        if keys is None:
            meta_dict["metadata"] = [(m.name, m.value, m.units) for m in self]
        else:
            meta_dict["metadata"] = [(m.name, m.value, m.units) for m in self if m.name in keys]
        return meta_dict

    def from_dict(self, meta_dict: dict):
        """Fill the metadata based on a dictionary.

        The dictionary that is expected can be generated from the :meth:`to_dict` method.

        Parameters
        ----------
        meta_dict
            Dictionary that contains all the key, value, units triples. This
            should use the same format as the output of the to_dict method.

        Examples
        --------
        >>> meta.add("Ben", "10", "kg")
        >>> meta_dict = meta.to_dict()
        >>> meta.clear()
        >>> len(meta)
        0
        >>> meta.from_dict(meta_dict)
        >>> print(meta)
        - {name: Ben, value: 10, units: kg}

        """
        for meta_tuple in meta_dict["metadata"]:
            try:
                self.add(*meta_tuple)
            except ValueError:
                pass
