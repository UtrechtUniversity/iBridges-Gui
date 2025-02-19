"""Interactive authentication with iRODS server."""

import os
import sys
from getpass import getpass
from pathlib import Path
from typing import Optional, Union

from ibridges.session import LoginError, PasswordError, Session

DEFAULT_IENV_PATH = Path(os.path.expanduser("~")).joinpath(".irods", "irods_environment.json")
DEFAULT_IRODSA_PATH = Path.home() / ".irods" / ".irodsA"


def interactive_auth(
    password: Optional[str] = None, irods_env_path: Union[None, str, Path] = None,
    **kwargs
) -> Session:
    """Interactive authentication with iRODS server.

    The main difference with using the :class:`ibridges.Session` object directly is
    that it will ask for your password if the cached password does not exist or is outdated.
    This can be more secure, since you won't have to store the password in a file or notebook.
    Caches the password in ~/.irods/.irodsA upon success.

    Parameters
    ----------
    password:
        Password to make the connection with. If not supplied, you will be asked interactively.
    irods_env_path:
        Path to the irods environment.

    Raises
    ------
    FileNotFoundError:
        If the irods_env_path does not exist.
    ValueError:
        If the connection to the iRods server cannot be established.

    Returns
    -------
        A connected session to the server.

    """
    if irods_env_path is None:
        irods_env_path = DEFAULT_IENV_PATH
    if not os.path.exists(irods_env_path):
        print(f"File not found: {irods_env_path}")
        raise FileNotFoundError

    session = None
    if DEFAULT_IRODSA_PATH.is_file() and password is None:
        session = _from_pw_file(irods_env_path, **kwargs)

    if password is not None:
        session = _from_password(irods_env_path, password, **kwargs)

    if session is not None:
        return session

    # If provided passwords in file or on prompt were wrong
    n_tries = 0
    success = False
    while not success and n_tries < 3:
        if sys.stdin.isatty() or 'ipykernel' in sys.modules:
            password = getpass('Your iRODS password: ')
        else:
            print('Your iRODS password: ')
            password = sys.stdin.readline().rstrip()
        try:
            session = Session(irods_env=irods_env_path, password=password, **kwargs)
            session.write_pam_password()
            success = True
            return session
        except PasswordError as e:
            print(repr(e))
            print("INFO: The provided password is wrong.")
            n_tries += 1
    raise LoginError("Connection to iRODS could not be established.")


def _from_pw_file(irods_env_path, **kwargs):
    try:
        session = Session(irods_env_path, **kwargs)
        return session
    except IndexError:
        print("INFO: The cached password in ~/.irods/.irodsA has been corrupted")
    except PasswordError:
        print("INFO: The cached password in ~/.irods/.irodsA is wrong.")
    return None


def _from_password(irods_env_path, password, **kwargs):
    try:
        session = Session(irods_env=irods_env_path, password=password, **kwargs)
        session.write_pam_password()
        return session
    except PasswordError:
        print("INFO: Wrong password.")
    return None
