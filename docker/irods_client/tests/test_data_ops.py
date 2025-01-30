import hashlib
import json
from pathlib import Path

import pytest

from ibridges.data_operations import apply_meta_archive, create_meta_archive, download, sync, upload
from ibridges.exception import DataObjectExistsError, NotACollectionError, NotADataObjectError
from ibridges.path import IrodsPath
from ibridges.util import is_collection, is_dataobject


def _get_digest(obj_or_file):
    with open(obj_or_file, "rb") as handle:
        digest = hashlib.sha256(handle.read()).digest()
    return digest

def _check_files_equal(*files):
    assert len(files) > 0
    digests = [_get_digest(f) for f in files]

    for dig in digests[1:]:
        if digests[0] != dig:
            return False
    return True


def _check_count(ops, nlist):
    for var, count, in zip(["create_collection", "create_dir", "download", "upload"],
                          nlist):
        assert len(getattr(ops, var)) == count



def test_upload_download_dataset(session, testdata):
    ipath = IrodsPath(session, "~", "plant.rtf")
    ipath.remove()
    ops = upload(session, testdata/"plant.rtf", IrodsPath(session, "~"))
    _check_count(ops, [0, 0, 0, 1])
    data_obj = ipath.dataobject
    assert is_dataobject(data_obj)
    assert not is_collection(data_obj)
    with pytest.raises(NotACollectionError):
        _ = ipath.collection

    # Check the overwrite and ignore_err parameters
    with pytest.raises(DataObjectExistsError):
        upload(session, testdata/"plant.rtf", IrodsPath(session))
    ops = upload(session, testdata/"plant.rtf", IrodsPath(session), overwrite=True)
    assert len(ops.upload) == 0
    with ipath.open("w") as handle:
        handle.write("test".encode())
    ops = upload(session, testdata/"plant.rtf", ipath, overwrite=False, ignore_err=True)
    assert len(ops.upload) == 0
    ops = upload(session, testdata/"plant.rtf", ipath, overwrite=True, ignore_err=True)
    assert len(ops.upload) == 1

    # Test downloading it back
    ops = download(session, ipath, testdata/"plant.rtf.copy", overwrite=True)
    assert _check_files_equal(testdata/"plant.rtf.copy", testdata/"plant.rtf")
    _check_count(ops, [0, 0, 1, 0])

    # Check overwrite and ignore_err parameters
    lpath = testdata/"plant.rtf.copy"
    ops = download(session, ipath, lpath, overwrite=True)
    assert len(ops.download) == 0
    with pytest.raises(FileExistsError):
        download(session, ipath, lpath)
    ops = download(session, ipath, lpath, overwrite=False, ignore_err=True)
    assert len(ops.download) == 0
    with ipath.open("w") as handle:
        handle.write("test".encode())
    ops = download(session, ipath, lpath, overwrite=True)
    assert len(ops.download) == 1
    ipath.remove()
    lpath.unlink()


def test_upload_download_collection(session, testdata, tmpdir):
    ipath = IrodsPath(session, "~", "test")
    ipath.remove()
    ops = upload(session, testdata, ipath)
    _check_count(ops, [3, 0, 0, 6])
    collection = ipath.collection
    assert is_collection(collection)
    assert not is_dataobject(collection)
    with pytest.raises(NotADataObjectError):
        ipath.dataobject

    # Check overwrite and ignore_err parameters
    with pytest.raises(DataObjectExistsError):
        upload(session, testdata, ipath)
    ops = upload(session, testdata, ipath, ignore_err=True)
    _check_count(ops, [0, 0, 0, 0])
    bunny_ipath = (ipath / "testdata" / "bunny.rtf")
    bunny_ipath.remove()
    ops = upload(session, testdata, ipath, overwrite=True)
    _check_count(ops, [0, 0, 0, 1])
    with bunny_ipath.open("w") as handle:
        handle.write("est".encode())
    ops = upload(session, testdata, ipath, overwrite=True)
    _check_count(ops, [0, 0, 0, 1])

    # Check if the downloaded collection is the same again.
    ops = download(session, ipath, tmpdir/"test")
    _check_count(ops, [0, 4, 6, 0])
    files = list(testdata.glob("*"))

    for cur_file in files:
        copy_file = Path(tmpdir, "test", cur_file)
        orig_file = Path(testdata, cur_file)
        if orig_file.is_file():
            with open(orig_file, "r") as handle:
                orig_data = handle.read()
            with open(copy_file, "r") as handle:
                copy_data = handle.read()
            assert copy_data == orig_data

    # Check overwrite and ignore_err parameters
    with pytest.raises(FileExistsError):
        download(session, ipath, tmpdir/"test")
    ops = download(session, ipath, tmpdir/"test", overwrite=True)
    _check_count(ops, [0, 0, 0, 0])
    with bunny_ipath.open("w") as handle:
        handle.write("testxx".encode())
    ops = download(session, ipath, tmpdir/"test", ignore_err=True)
    _check_count(ops, [0, 0, 0, 0])
    ops = download(session, ipath, tmpdir/"test", overwrite=True)
    _check_count(ops, [0, 0, 1, 0])
    ipath.remove()


def test_meta_archive(session, testdata, tmpdir):
    ipath = IrodsPath(session, "test")
    ipath.remove()
    sync(session, testdata, ipath)
    assert len(list(ipath.meta)) == 0
    meta_list = [
        (ipath, ("root", "true", "")),
        (ipath / "more_data", ("more_data", "false", "kg")),
        (ipath / "more_data" / "polarbear.txt", ("is_polar", "true", "bool")),
    ]
    for cur_ipath, meta_data in meta_list:
        cur_ipath.meta.add(*meta_data)
    meta_fp = tmpdir / "meta.json"
    create_meta_archive(session, ipath, meta_fp)
    with open(meta_fp, "r") as handle:
        meta_dict = json.load(handle)

    assert "ibridges_metadata_version" in meta_dict
    assert meta_dict["recursive"] is True
    assert meta_dict["root_path"] == str(ipath)
    assert len(meta_dict["items"]) == 8

    def _find_meta_dict(abs_path):
        rel_path = abs_path.relative_to(ipath)
        for item in meta_dict["items"]:
            if item["rel_path"] == str(rel_path):
                return item
        raise ValueError("Cannot find item in dictionary.")

    def _check_in_metadict(expected_metadata, retrieved_metadata):
        for meta_item in retrieved_metadata:
            if all(meta_item[i] == expected_metadata[i] for i in range(len(expected_metadata))):
                return True
        return False

    # Check if the metadata is in the file, then delete it remotely
    for cur_ipath, meta_data in meta_list:
        print(cur_ipath)
        cur_meta_dict = _find_meta_dict(cur_ipath)
        assert _check_in_metadict(meta_data, cur_meta_dict["metadata"])
        # assert meta_data in cur_meta_dict["metadata"]
        cur_ipath.meta.delete(meta_data[0], meta_data[1])

    # Apply the archive and see if it has arrived.
    apply_meta_archive(session, meta_fp, ipath)

    for cur_ipath, meta_data in meta_list:
        assert meta_data in cur_ipath.meta
