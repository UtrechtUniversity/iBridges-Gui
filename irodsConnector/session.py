""" session operations
"""
import warnings
import os
import json
import irods.session
from irods.exception import NetworkException
from .keywords import exceptions

class Session:
    """Irods session authentication.

    """

    def __init__(self, irods_env: dict=None, irods_env_path: str='', 
                 password: str='') -> irods.session:
        """ iRODS authentication with Python client.

        Parameters
        ----------
        irods_conf: dict
            Dictionary from irods_environment.json
        password : str
            Plain text password.

        """
        if irods_env == None and irods_env_path == '':
            raise Exception("CONNECTION ERROR: no irods environment given.")
        if irods_env and irods_env_path:
            warnings.warn("Environment dictionary will be overwritten with irods environment file")
        if irods_env_path:
            with open(os.path.expanduser("~/.irods/irods_environment.json"), "r") as f:
                irods_ienv = json.load(f)

        self._password = password
        self._irods_env = irods_env
        self._irods_env_path = irods_env_path
        self._irods_session = self.connect()

    def __del__(self):
        del self.irods_session

    @property
    def irods_session(self) -> irods.session.iRODSSession:
        """iRODS session creation.

        Returns
        -------
        iRODSSession
            iRODS connection based on the current environment and password.

        """
        return self._irods_session

    @irods_session.deleter
    def irods_session(self):
        """Properly delete iRODS session.
        """
        if self._irods_session is not None:
            # In case the iRODS session is not fully there.
            try:
                self._irods_session.cleanup()
            except NameError:
                pass
            except AttributeError:
                pass
            del self._irods_session
            self._irods_session = None

    # Authentication workflow methods
    #

    def has_valid_irods_session(self) -> bool:
        """Check if the iRODS session is valid.

        Returns
        -------
        bool
            Is the session valid?

        """
        return self.server_version != ()

    def connect(self):
        """Establish an iRODS session.

        """
        user = self._irods_env.get('irods_user_name', '')
        if user == 'anonymous':
            try:
                # TODO: implement and test for SSL enabled iRODS
                logging.debug('iRODS LOGIN of anonymous user')
                # self._irods_session = iRODSSession(user='anonymous',
                #                        password='',
                #                        zone=zone,
                #                        port=1247,
                #                        host=host)
                assert False
            except Exception:
                logging.error('Anonymous LOGIN FAILED: %s', 'Not implemented')
                return {'successful': False, 'reason': 'Not implemented'}
        else:  # authentication with irods environment and password
            if self._password == '':
                print("Auth without password")
                # use cached password of .irodsA built into prc
                return self.authenticate_using_auth_file()
            else:
                print("Auth with password")
                # irods environment and given password
                logging.info('FULL ENVIRONMENT SESSION')
                return self.authenticate_using_password()

    def authenticate_using_password(self):
        try:
            self._irods_session = irods.session.iRODSSession(password=self._password,
                                                             **self._irods_env)
            assert self._irods_session.server_version != ()
            logging.info('IRODS LOGIN SUCCESS: %s:%s',
                         self._irods_session.host, self._irods_session.port)
            return self._irods_session
        except ValueError as e:
            logging.error('FULL ENVIRONMENT LOGIN FAILED: %r', e)
            raise Exception("Unexpected value in irods_environment.json; "+repr(e))
        except NetworkException as e:
            logging.error('FULL ENVIRONMENT LOGIN FAILED: %r', e)
            raise Exception("Host, port or irods_client_server_negotiation not set correctly in irods_environment.json; "+repr(e))
        except Exception as e:
            logging.error('FULL ENVIRONMENT LOGIN FAILED: %r', e)
            if repr(e) in exceptions:
                raise Exception(exceptions[repr(e)]+"; "+repr(e))
            else:
                raise e

    def authenticate_using_auth_file(self):
        logging.info('AUTH FILE SESSION')
        try:
            self._irods_session = irods.session.iRODSSession(
                    irods_env_file=self._irods_env_path)
            assert self._irods_session.server_version != ()
            logging.info('IRODS LOGIN SUCCESS: %s:%s',
                         self._irods_session.host, self._irods_session.port)
            return self._irods_session
        except ValueError as e:
            logging.error('FULL ENVIRONMENT LOGIN FAILED: %r', e)
            raise Exception("Unexpected value in irods_environment.json; "+repr(e))
        except NetworkException as e:
            logging.error('FULL ENVIRONMENT LOGIN FAILED: %r', e)
            raise Exception("Host, port or irods_client_server_negotiation not set correctly in irods_environment.json; "+repr(e))
        except Exception as e:
            logging.error('AUTH FILE LOGIN FAILED')
            logging.error('Have you set the iRODS environment file correctly?')
            print(repr(e))
            if repr(e) in exceptions:
                raise Exception(exceptions[repr(e)]+"; "+repr(e))
            else:
                raise e

    @property
    def default_resc(self) -> str:
        """Default resource name from iRODS environment.

        Returns
        -------
        str
            Resource name.

        """
        if self._irods_session:
            return self._irods_session.default_resource
        return ''

    @property
    def host(self) -> str:
        """Retrieve hostname of the iRODS server.

        Returns
        -------
        str
            Hostname.

        """
        if self._irods_session:
            return self._irods_session.host
        return ''

    @property
    def port(self) -> str:
        """Retrieve port of the iRODS server.

        Returns
        -------
        str
            Port.

        """
        if self._irods_session:
            return self._irods_session.port
        return ''

    @property
    def server_version(self) -> tuple:
        """Retrieve version of the iRODS server

        Returns
        -------
        tuple
            Server version: (major, minor, patch).

        """
        try:
            return self._irods_session.server_version
        except Exception as e:
            if repr(e) in exceptions:
                raise Exception(exceptions[repr(e)])
            else:
                raise e

    @property
    def username(self) -> str:
        """Retrieve username.

        Returns
        -------
        str
            Username.

        """
        if self._irods_session:
            return self._irods_session.username
        return ''

    @property
    def zone(self) -> str:
        """Retrieve the zone name.

        Returns
        -------
        str
            Zone.

        """
        if self._irods_session:
            return self._irods_session.zone
        return ''
