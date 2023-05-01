#!/usr/bin/env python3
"""iBridges GUI startup script.

"""
import logging
import os
import setproctitle
import sys

import irods.exception
import PyQt6.QtCore
import PyQt6.QtGui
import PyQt6.QtWidgets
import PyQt6.uic

import gui
import irodsConnector
import utils

app = PyQt6.QtWidgets.QApplication(sys.argv)
widget = PyQt6.QtWidgets.QStackedWidget()

# Work around a PRC XML issue handling special characters
os.environ['PYTHON_IRODSCLIENT_DEFAULT_XML'] = 'QUASI_XML'


class IrodsLoginWindow(PyQt6.QtWidgets.QDialog,
                       gui.ui_files.irodsLogin.Ui_irodsLogin,
                       utils.context.ContextContainer):
    """Definition and initialization of the iRODS login window.

    """
    icommands = False
    this_application = ''

    def __init__(self):
        super().__init__()
        self.ibridges_path = utils.path.LocalPath(utils.context.IBRIDGES_DIR).expanduser()
        self.irods_path = utils.path.LocalPath(utils.context.IRODS_DIR).expanduser()
        self._load_gui()
        self._init_logging()
        self._init_envbox()
        self._init_password()

    def _load_gui(self):
        """

        """
        if getattr(sys, 'frozen', False):
            super().setupUi(self)
        else:
            PyQt6.uic.loadUi("gui/ui_files/irodsLogin.ui", self)
        self.selectIcommandsButton.toggled.connect(self.setup_icommands)
        self.standardButton.toggled.connect(self.setup_standard)
        self.connectButton.clicked.connect(self.login_function)
        self.ticketButton.clicked.connect(self.ticket_login)
        self.passwordField.setEchoMode(PyQt6.QtWidgets.QLineEdit.EchoMode.Password)

    def _init_logging(self):
        """

        """
        utils.utils.setup_logger(self.ibridges_path, self.context.application_name)

    def _init_envbox(self):
        """Populate environment drop-down.

        """
        env_jsons = [
            path.name for path in
            self.irods_path.glob('irods_environment*json')]
        if len(env_jsons) == 0:
            self.envError.setText(f'ERROR: no "irods_environment*json" files found in {self.irods_path}')
        self.envbox.clear()
        self.envbox.addItems(env_jsons)
        envname = ''
        if 'last_ienv' in self.conf and self.conf['last_ienv'] in env_jsons:
            envname = self.conf['last_ienv']
        elif 'irods_environment.json' in env_jsons:
            envname = 'irods_environment.json'
        index = 0
        if envname:
            index = self.envbox.findText(envname)
        self.envbox.setCurrentIndex(index)

    def _init_password(self):
        """

        """
        if self.conn.password:
            self.passwordField.setText(self.conn.password)

    def _reset_mouse_and_error_labels(self):
        """Reset cursor and clear error text

        """
        self.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.ArrowCursor))
        self.passError.setText('')
        self.envError.setText('')

    def setup_standard(self):
        """Check the state of the radio button for using the pure Python
        client.

        """
        if self.standardButton.isChecked():
            self._init_envbox()
            self.icommands = False

    def setup_icommands(self):
        """Check the state of the radio button for using iCommands.
        This includes a check for the existance of the iCommands on the
        current system.

        """
        if self.selectIcommandsButton.isChecked():
            self.icommandsError.setText('')
            if self.conn.icommands:
                self.icommands = True
                # TODO support arbitrary iRODS environment file for iCommands
            else:
                self.icommandsError.setText('ERROR: no iCommands found')
                self.standardButton.setChecked(True)

    def login_function(self):
        """Check connectivity and log in to iRODS handling common errors.

        """
        # Replacement connector (required for new sessions)
        if not self.context.irods_connector:
            self.context.irods_connector = irodsConnector.manager.IrodsConnector()
        irods_env_file = self.irods_path.joinpath(self.envbox.currentText())
        self.context.irods_env_file = irods_env_file
        print(f'IRODS ENVIRONMENT FILE SET: {irods_env_file.name}')
        self.envError.setText('')
        if not (self.ienv and self.context.ienv_is_complete()):
            self.context.irods_environment.reset()
            self.passError.clear()
            self.envError.setText('ERROR: iRODS environment missing or incomplete.')
            self.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.ArrowCursor))
            return
        if not utils.utils.can_connect(self.ienv['irods_host']):
            logging.info('iRODS login: No network connection to server')
            self.envError.setText('No network connection to server')
            self.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.ArrowCursor))
            return
        self.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.WaitCursor))
        self.conf['last_ienv'] = irods_env_file.name
        self.context.save_ibridges_configuration()
        password = self.passwordField.text()
        try:
            self.conn.password = password
            # widget is a global variable
            browser = gui.mainmenu.mainmenu(widget)
            if len(widget) == 1:
                widget.addWidget(browser)
            self._reset_mouse_and_error_labels()
            # self.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.ArrowCursor))
            widget.setCurrentIndex(widget.currentIndex()+1)
        except (irods.exception.CAT_INVALID_AUTHENTICATION,
                irods.exception.PAM_AUTH_PASSWORD_FAILED,
                irods.exception.CAT_INVALID_USER,
                ConnectionRefusedError):
            self.envError.clear()
            self.passError.setText('ERROR: Wrong password.')
            self.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.ArrowCursor))
        except irods.exception.CAT_PASSWORD_EXPIRED:
            self.envError.clear()
            self.passError.setText('ERROR: Cached password expired. Re-enter password.')
            self.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.ArrowCursor))
        except irods.exception.NetworkException:
            self.passError.clear()
            self.envError.setText('iRODS server ERROR: iRODS server down.')
            self.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.ArrowCursor))
        except Exception as unknown:
            message = f'Something went wrong: {unknown}'
            logging.exception(message)
            # logging.info(repr(error))
            self.envError.setText(message)
            self.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.ArrowCursor))

    def ticket_login(self):
        """Log in to iRODS using a ticket.

        """
        # widget is a global variable
        browser = gui.mainmenu.mainmenu(widget)
        browser.menuOptions.clear()
        browser.menuOptions.deleteLater()
        if len(widget) == 1:
            widget.addWidget(browser)
        self._reset_mouse_and_error_labels()
        # self.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.ArrowCursor))
        widget.setCurrentIndex(widget.currentIndex()+1)


def closeClean():

    context = utils.context.Context()
    if context.irods_connector:
        context.irods_connector.cleanup()


def main():
    """Main function

    """
    context = utils.context.Context()
    context.application_name = 'iBridges'
    context.irods_connector = irodsConnector.manager.IrodsConnector()
    setproctitle.setproctitle(context.application_name)
    login_window = IrodsLoginWindow()
    login_window.this_application = context.application_name
    widget.addWidget(login_window)
    widget.show()
    # app.setQuitOnLastWindowClosed(False)
    app.lastWindowClosed.connect(closeClean)
    app.exec()


if __name__ == "__main__":
    main()
