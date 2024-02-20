import pytest
from irods.exception import CAT_NO_ACCESS_PERMISSION
from pytest import mark

from ibridges.irodsconnector.data_operations import download, upload
from ibridges.irodsconnector.permissions import Permissions
from ibridges.utils.path import IrodsPath


@mark.parametrize("item_name", ["collection", "dataobject"])
def test_perm_own(session, item_name, request, tmpdir, config):
    item = request.getfixturevalue(item_name)
    perm = Permissions(session, item)
    ipath = IrodsPath(session, item.path)

    assert isinstance(str(perm), str)
    assert isinstance(perm.available_permissions, dict)
    with pytest.raises(ValueError):
        perm.set("null", user=session.username, zone=session.zone)
    perm.set("read")
    with pytest.raises(ValueError):
        upload(session, tmpdir/"bunny.rt.copy", ipath, overwrite=True)
    perm.set("own")

@mark.parametrize("item_name", ["collection", "dataobject"])
def test_perm_user(session, item_name, request, config):
    # Testing access for another user if defined in config.toml
    testuser = config.get("test_user", None)
    item = request.getfixturevalue(item_name)
    perm = Permissions(session, item)
    if testuser:
        ipath = IrodsPath(session, item.path)
        perm.set("read", user=testuser, zone=session.zone)
        assert testuser in [p.user_name for p in perm]
        assert (testuser, 1050) in [(p.user_name, p.to_int(p.access_name)) for p in perm]
        perm.set("write", user=testuser, zone=session.zone)
        assert (testuser, 1120) in [(p.user_name, p.to_int(p.access_name)) for p in perm]
        perm.set("null", user=testuser, zone=session.zone)
        assert testuser not in [p.user_name for p in perm]
