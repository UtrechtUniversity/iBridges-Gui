"""For creating sessions non-interactively."""

from __future__ import annotations

import json
import os
import socket
import warnings
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional, Union

import irods.session
from irods.exception import (
    CAT_INVALID_AUTHENTICATION,
    CAT_INVALID_USER,
    CAT_PASSWORD_EXPIRED,
    PAM_AUTH_PASSWORD_FAILED,
    NetworkException,
)
from irods.session import NonAnonymousLoginWithoutPassword, iRODSSession

from ibridges import icat_columns as icat

APP_NAME = "ibridges"


class Session:
    """Session to connect and perform operations on the iRODS server.

    When the session is initialized, you are connected succesfully to the iRODS server.
    Most likely you will need to supply a password to the initialization routine. This
    can be problematic from a security standpoint (the password might be recorded for others
    to see). In this case, you should use the :func:`ibridges.interactive.interactive_auth`
    function, which will ask for your password and not store it.

    The Session object is a context manager, so using it using the :code:`with` statement
    is generally preferred, see examples below. Otherwise, the user is responsible for closing
    the connection using the :meth:`close` method.

    Parameters
    ----------
    irods_env:
        iRODS environment (irods_environment.json) file, or a dictionary containing its contents.
    password:
        Pass the password as a string. By default None, in which case it will try to
        use the cached password. If this fails, the initialization will fail and throw an exception.
    irods_home:
        Override the home directory of irods. Otherwise attempt to retrive the value
        from the irods environment dictionary. If it is not there either, then use
        /{zone}/home/{username}.

    Raises
    ------
    FileNotFoundError:
        If the irods_env parameter is interpreted as a file name and not found.
    TypeError:
        If the irods_env parameter is not a dict, str or Path.
    LoginError:
        If the connection to the iRODS server fails to establish.

    Examples
    --------
    >>> session = Session(Path.home() / ".irods" / "irods_environment.json",
    >>>                    password="your_password", irods_home="/zone/home/user")
    >>> session = Session(env_dictionary)  # env_dictionary with connection info
    >>> with Session("irods_environment.json") as session:
    >>>     # Do operations with the session here.
    >>>     # The session will be automatically closed on finish/error.

    """  # noqa: D403"""

    def __init__(
        self,
        irods_env: Union[dict, str, Path],
        password: Optional[str] = None,
        irods_home: Optional[str] = None,
        cwd: Optional[str] = None,
    ):
        """Authenticate and connect to the iRODS server."""
        irods_env_path = None
        if isinstance(irods_env, (str, Path)):
            irods_env_path = Path(irods_env)
            if not irods_env_path.is_file():
                raise FileNotFoundError(f"Cannot find irods environment file '{irods_env}'")
            with irods_env_path.open("r", encoding="utf-8") as envfd:
                irods_env = json.load(envfd)
        if not isinstance(irods_env, dict):
            raise TypeError(
                f"Error reading environment file '{irods_env_path}': "
                f"expected dictionary, got {type(irods_env)}."
            )
        try:
            self.connection_timeout = int(irods_env.pop("connection_timeout", 25000))
        except TypeError as err:
            raise ValueError("'connection_timeout' in irods_environment must be integer.") from err

        self._password = password
        self._irods_env: dict = irods_env
        self._irods_env_path = irods_env_path
        self.irods_session = self.connect()
        if irods_home is not None:
            self.home = irods_home
        if "irods_home" not in self._irods_env:
            self.home = "/" + self.zone + "/home/" + self.username

        if cwd is not None:
            self.cwd = cwd
        else:
            self.cwd = self.home

    def __enter__(self):
        """Connect to the iRODS server if not already connected."""
        if not self.has_valid_irods_session():
            self.connect()
        return self

    def __exit__(self, exc_type, exc_value, exc_trace_back):
        """Disconnect from the iRODS server."""
        self.close()

    @property
    def home(self) -> str:
        """Current working directory for irods.

        In the iRODS community this is known as 'irods_home', in file system terms
        it would be the current working directory.

        Returns
        -------
        str:
            The current working directory in the current session.

        Examples
        --------
        >>> session.home
        /zone/home/user

        """
        return self._irods_env["irods_home"]

    @home.setter
    def home(self, value):
        self._irods_env["irods_home"] = value

    # Authentication workflow methods
    def has_valid_irods_session(self) -> bool:
        """Check if the iRODS session is valid.

        Returns
        -------
        bool:
            True if the session is valid, False otherwise.

        """
        return self.irods_session is not None and self.server_version != ()

    @classmethod
    def network_check(cls, hostname: str, port: int) -> bool:
        """Check connectivity to an iRODS server.

        This method attempts to reach the iRODS server, without
        supplying any user credentials.

        Parameters
        ----------
        hostname : str
            FQDN/IP of an iRODS server.
        port : int
            Port to which to connect to the server

        Returns
        -------
            Connection to `hostname` possible.

        """
        if hostname is None or port is None:
            raise LoginError("No host or port set in environment file.")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.settimeout(10.0)
                sock.connect((hostname, int(port)))
                return True
            except socket.error:
                return False

    def connect(self) -> iRODSSession:
        """Establish an iRODS session.

        Users generally don't need to call this connect function
        manually, except if they called the :meth:`close` explicitly
        and want to reconnect. If you call the connect method multiple times
        without disconnecting, this might result in stale connections to the iRODS
        server.

        Returns
        -------
            A python-irodsclient session. This is also stored in the ibridges.Session
            object itself, so users do not need to store this session themselves.

        """
        irods_host = self._irods_env.get("irods_host", None)
        irods_port = self._irods_env.get("irods_port", None)
        network = self.network_check(irods_host, irods_port)
        if network is False:
            raise ConnectionError(f"No internet connection to {irods_host} and port {irods_port}")
        user = self._irods_env.get("irods_user_name", "")
        if user == "anonymous":
            # TODOx: implement and test for SSL enabled iRODS
            # self.irods_session = iRODSSession(user='anonymous',
            #                        password='',
            #                        zone=zone,
            #                        port=1247,
            #                        host=host)
            raise NotImplementedError
        # authentication with irods environment and password
        if self._password is None or self._password == "":
            # use cached password of .irodsA built into prc
            # print("Auth without password")
            return self.authenticate_using_auth_file()

        # irods environment and given password
        # print("Auth with password")
        return self.authenticate_using_password()

    def close(self):
        """Disconnect the iRODS session.

        This closes the connection, and makes the session available for
        reconnection with the :meth:`connect` method.
        """
        if self.irods_session is not None:
            self.irods_session.do_configure = {}
            self.irods_session.cleanup()
            self.irods_session = None

    def authenticate_using_password(self) -> iRODSSession:
        """Authenticate with the iRODS server using a password.

        Internal use only.
        """
        try:
            irods_session = irods.session.iRODSSession(
                password=self._password,
                **self._irods_env,
                connection_timeout=self.connection_timeout,
                application_name=APP_NAME,
            )
            _ = irods_session.server_version
        except Exception as e:
            raise _translate_irods_error(e) from e
        if irods_session.server_version == ():
            raise LoginError("iRODS server does not return a server version.")
        return irods_session

    def authenticate_using_auth_file(self) -> iRODSSession:
        """Authenticate with an authentication file.

        Internal use only.
        """
        try:
            if self._irods_env_path is not None:
                irods_session = irods.session.iRODSSession(
                    irods_env_file=self._irods_env_path,
                    application_name=APP_NAME,
                    connection_timeout=self.connection_timeout,
                )
            else:
                # Create a temporary file for the irods environment dictionary.
                # From Python 3.12 we could use the delete_on_close parameter.
                with NamedTemporaryFile(delete=False, mode="w") as handle:
                    temp_ienv_path = handle.name
                    try:
                        handle.write(json.dumps(self._irods_env))
                        handle.close()
                        irods_session = irods.session.iRODSSession(
                            irods_env_file=temp_ienv_path,
                            application_name=APP_NAME,
                            connection_timeout=self.connection_timeout,
                        )
                    finally:
                        os.unlink(temp_ienv_path)
            _ = irods_session.server_version  # pylint: disable=possibly-used-before-assignment
        except NonAnonymousLoginWithoutPassword as e:
            raise ValueError("No cached password found.") from e
        except Exception as e:
            raise _translate_irods_error(e) from e
        if irods_session.server_version == ():
            raise LoginError("iRODS server does not return a server version.")
        return irods_session

    def write_pam_password(self):
        """Store the password in the iRODS authentication file in obfuscated form.

        Internal use only.
        """
        connection = self.irods_session.pool.get_connection()
        pam_passwords = self.irods_session.pam_pw_negotiated
        if len(pam_passwords):
            actual_password = pam_passwords[0]
        else:
            actual_password = self._password
        if actual_password:
            irods_auth_file = self.irods_session.get_irods_password_file()
            with open(irods_auth_file, "w", encoding="utf-8") as authfd:
                authfd.write(irods.password_obfuscation.encode(actual_password))
        else:
            warnings.warn("WARNING -- unable to cache obfuscated password locally")
        connection.release()

    @property
    def default_resc(self) -> str:
        """Default resource name from iRODS environment.

        Returns
        -------
        str:
            Name of the default resource.

        """
        if self.irods_session:
            try:
                return self.irods_session.default_resource
            except AttributeError:
                pass
        raise ValueError("'irods_default_resource' not set in iRODS configuration.")

    def __getattr__(self, item):
        """Pass through a few attributes from irods_session."""
        if item in ["host", "port", "username", "zone"]:
            if self.irods_session is None:
                raise AttributeError("Need a valid iRODS session to get '{item}'.")
            return getattr(self.irods_session, item)
        return super().__getattribute__(item)

    @property
    def server_version(self) -> tuple:
        """Retrieve version of the iRODS server.

        Returns
        -------
            Server version: (major, minor, patch).

        """
        try:
            return self.irods_session.server_version
        except Exception as e:
            raise _translate_irods_error(e) from e

    def get_user_info(self) -> tuple[list, list]:
        """Query for user type and groups.

        Returns
        -------
            Tuple containing (iRODS user type names, iRODS group names)

        """
        query = self.irods_session.query(icat.USER_TYPE).filter(
            icat.LIKE(icat.USER_NAME, self.username)
        )
        user_type = [list(result.values())[0] for result in query.get_results()][0]
        query = self.irods_session.query(icat.USER_GROUP_NAME).filter(
            icat.LIKE(icat.USER_NAME, self.username)
        )
        user_groups = [list(result.values())[0] for result in query.get_results()]
        return user_type, user_groups


class LoginError(AttributeError):
    """Error indicating a failure to log into the iRODS server due to the configuration."""


class PasswordError(ValueError):
    """Error indicating failure to log into the iRODS server due to wrong or outdated password."""


def _translate_irods_error(exc) -> Exception:  # pylint: disable=too-many-return-statements
    if isinstance(exc, NetworkException):
        if any((a.startswith("Client-Server negotiation failure") for a in exc.args)):
            return LoginError(
                "Host, port, irods_client_server_policy or "
                "irods_client_server_negotiation not set correctly in "
                "irods_environment.json"
            )
    if isinstance(exc, TypeError):
        return LoginError(f"Add info to irods_environment.json: {exc.args}")
    if isinstance(exc, CAT_INVALID_USER):
        return PasswordError("User credentials are not accepted")
    if isinstance(exc, PAM_AUTH_PASSWORD_FAILED):
        return PasswordError("Wrong password")
    if isinstance(exc, CAT_PASSWORD_EXPIRED):
        return PasswordError("Cached password is expired")
    if isinstance(exc, CAT_INVALID_AUTHENTICATION):
        return PasswordError("Cached password is wrong")
    if isinstance(exc, ValueError):
        # PRC 2.0.0 does not make a difference between wrong password or expired pw
        if exc.args[0] == "Authentication failed: scheme = 'pam', auth_type = None":
            return PasswordError("Cached password is expired", "Wrong password provided")
        return LoginError("Unexpected value in irods_environment; ")
    return LoginError("Unknown problem creating irods session.")
