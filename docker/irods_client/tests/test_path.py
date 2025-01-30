import pytest
from irods.exception import DataObjectDoesNotExist

from ibridges.exception import NotADataObjectError
from ibridges.path import IrodsPath


def test_path_open_error(session, collection):
    ipath = IrodsPath(session, "open_err_test.txt")
    ipath.remove()
    coll_ipath = IrodsPath(session, collection.path)

    # Reading data objects that do no exist should raise an error.
    with pytest.raises(DataObjectDoesNotExist):
        with ipath.open("r") as handle:
            handle.read()

    with pytest.raises(DataObjectDoesNotExist):
        with ipath.open("a") as handle:
            handle.write("abc")

    # We should not be able to open collections.
    with pytest.raises(NotADataObjectError):
        with coll_ipath.open("r") as handle:
            handle.read()

    ipath.remove()


def test_path_open(session):
    ipath = IrodsPath(session, "open_test.txt")
    ipath.remove()

    test_str_1 = "This is a test."
    test_str_2 = "\nAnother test."

    with ipath.open("w") as handle:
        handle.write(test_str_1.encode("utf-8"))

    with ipath.open("r") as handle:
        cur_str = handle.read().decode("utf-8")
        assert cur_str == test_str_1

    with ipath.open("a") as handle:
        handle.write(test_str_2.encode("utf-8"))

    with ipath.open("r") as handle:
        assert handle.read().decode("utf-8") == test_str_1 + test_str_2
