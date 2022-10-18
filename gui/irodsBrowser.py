"""Browser tab.

"""
import logging
import pathlib

import irods.exception
from irods.path import iRODSPath
import PyQt6.QtCore
import PyQt6.QtGui
import PyQt6.QtWidgets

import gui
import meta
import utils


class irodsBrowser():
    """

    """

    def __init__(self, widget, ic):
        """

        """
        self.force = ic.ienv.get('force_unknown_free_space', False)
        self.ic = ic
        self.widget = widget
        self.widget.viewTabs.setCurrentIndex(0)
        # Browser table
        self.widget.collTable.setColumnWidth(1, 399)
        self.widget.collTable.setColumnWidth(2, 199)
        self.widget.collTable.setColumnWidth(3, 399)
        self.widget.collTable.setColumnWidth(0, 20)
        # Metadata table
        self.widget.metadataTable.setColumnWidth(0, 199)
        self.widget.metadataTable.setColumnWidth(1, 199)
        self.widget.metadataTable.setColumnWidth(2, 199)
        # ACL table
        self.widget.aclTable.setColumnWidth(0, 299)
        self.widget.aclTable.setColumnWidth(1, 299)
        # If user is not admin nor datasteward, hide ACL buttons.
        try:
            user_type, user_groups = ic.get_user_info()
        except irods.exception.NetworkException:
            self.widget.errorLabel.setText(
                    "IRODS NETWORK ERROR: No Connection, please check network")
        # TODO : in a local docker environment these conditions are not met. 
        # Still it would be nice to be able to test the full features even if one is not 
        # rodsadmin
        if user_type != 'rodsadmin' and \
           'datastewards' not in user_groups and \
           'training' not in user_groups:
            self.widget.aclAddButton.hide()
            self.widget.aclBox.setEnabled(False)
            self.widget.recurseBox.setEnabled(False)
        # Resource table
        self.widget.resourceTable.setColumnWidth(0, 500)
        self.widget.resourceTable.setColumnWidth(1, 90)
        # iRODS defaults
        if 'irods_cwd' in ic.ienv:
            root_path = ic.ienv['irods_cwd']
        elif 'irods_home' in ic.ienv:
            root_path = ic.ienv['irods_home']
        else:
            root_path = f'/{ic.session.zone}/home/{ic.session.username}'
        try:
            self.root_coll = ic.get_collection(root_path)
        except irods.exception.CollectionDoesNotExist:
            self.root_coll = ic.get_collection(f'/{ic.session.zone}/home')
        except irods.exception.NetworkException:
            self.widget.errorLabel.setText(
                'IRODS NETWORK ERROR: No Connection, please check network')
        self.currentBrowserRow = 0
        self.browse()   # defines the signals and slots  
        self.resetPath()

    def browse(self):
        # update main table when iRODS path is changed upon 'Enter'
        self.widget.inputPath.returnPressed.connect(self.loadTable)
        self.widget.inputPath.textChanged.connect(self.loadTable)
        
        self.widget.homeButton.clicked.connect(self.resetPath)
        
        # quick data upload and download (files only)
        self.widget.UploadButton.clicked.connect(self.fileUpload)
        self.widget.DownloadButton.clicked.connect(self.fileDownload)
        
        # new collection
        self.widget.createCollButton.clicked.connect(self.createCollection)
        self.widget.dataDeleteButton.clicked.connect(self.deleteData)
        self.widget.loadDeleteSelectionButton.clicked.connect(self.loadSelection)
        
        # functionality to lower tabs for metadata, acls and resources
        self.widget.collTable.doubleClicked.connect(self.updatePath)
        self.widget.collTable.clicked.connect(self.fillInfo)
        self.widget.metadataTable.clicked.connect(self.editMetadata)
        self.widget.aclTable.clicked.connect(self.editACL)
        # actions to update iCat entries of metadata and acls
        self.widget.metaAddButton.clicked.connect(self.addIcatMeta)
        self.widget.metaUpdateButton.clicked.connect(self.updateIcatMeta)
        self.widget.metaDeleteButton.clicked.connect(self.deleteIcatMeta)
        self.widget.metaLoadFile.clicked.connect(self.loadMetadataFile)
        self.widget.aclAddButton.clicked.connect(self.updateIcatAcl)
        
    # Util functions
    def _clear_error_label(self):
        """Clear any error text.

        """
        self.widget.errorLabel.clear()

    def _clear_view_tabs(self):
        """Clear the tabs view.

        """
        self.widget.aclTable.setRowCount(0)
        self.widget.metadataTable.setRowCount(0)
        self.widget.resourceTable.setRowCount(0)
        self.widget.previewBrowser.clear()

    def _fill_resources_tab(self, obj_path):
        """Populate the table in the Resources tab with the resource
        hierarchy of the replicas of the selected data object.

        Parameters
        ----------
        obj_path : str
            Path of iRODS collection or data object selected.
        
        """
        self.widget.resourceTable.setRowCount(0)
        if self.ic.dataobject_exists(obj_path):
            obj = self.ic.get_dataobject(obj_path)
            hierarchies = [repl.resc_hier for repl in obj.replicas]
            self.widget.resourceTable.setRowCount(len(hierarchies))
            for index, hierarchy in enumerate(hierarchies):
                self.widget.resourceTable.setItem(
                    index, 0, PyQt6.QtWidgets.QTableWidgetItem(hierarchy))
        self.widget.resourceTable.resizeColumnsToContents()

    def _fill_acls_tab(self, obj_path):
        """Populate the table in the ACLs tab.

        Parameters
        ----------
        obj_path : str
            Path of iRODS collection or data object selected.
        
        """
        self.widget.aclTable.setRowCount(0)
        self.widget.aclUserField.clear()
        self.widget.aclZoneField.clear()
        self.widget.aclBox.setCurrentText("----")
        obj = None
        if self.ic.collection_exists(obj_path):
            obj = self.ic.session.collections.get(obj_path)
        elif self.ic.dataobject_exists(obj_path):
            obj = self.ic.session.data_objects.get(obj_path)
        if obj is not None:
            acls = self.ic.session.permissions.get(obj)
            self.widget.aclTable.setRowCount(len(acls))
            for row, acl in enumerate(acls):
                acl_access_name = self.ic.permissions[acl.access_name]
                self.widget.aclTable.setItem(
                    row, 0, PyQt6.QtWidgets.QTableWidgetItem(acl.user_name))
                self.widget.aclTable.setItem(
                    row, 1, PyQt6.QtWidgets.QTableWidgetItem(acl.user_zone))
                self.widget.aclTable.setItem(
                    row, 2, PyQt6.QtWidgets.QTableWidgetItem(acl_access_name))
        self.widget.aclTable.resizeColumnsToContents()

    def _fill_metadata_tab(self, obj_path):
        """Populate the table in the metadata tab.

        Parameters
        ----------
        obj_path : str
            Full name of iRODS collection or data object selected.
        
        """
        self.widget.metaKeyField.clear()
        self.widget.metaValueField.clear()
        self.widget.metaUnitsField.clear()
        
        obj = None
        if self.ic.collection_exists(obj_path):
            obj = self.ic.session.collections.get(obj_path)
        elif self.ic.dataobject_exists(obj_path):
            obj = self.ic.session.data_objects.get(obj_path)
        if obj is not None:
            metadata = obj.metadata.items()
            self.widget.metadataTable.setRowCount(len(metadata))
            for row, avu in enumerate(metadata):
                self.widget.metadataTable.setItem(
                    row, 0, PyQt6.QtWidgets.QTableWidgetItem(avu.name))
                self.widget.metadataTable.setItem(
                    row, 1, PyQt6.QtWidgets.QTableWidgetItem(avu.value))
                self.widget.metadataTable.setItem(
                    row, 2, PyQt6.QtWidgets.QTableWidgetItem(avu.units))
        self.widget.metadataTable.resizeColumnsToContents()

    def _fill_preview_tab(self, obj_path):
        """Populate the table in the metadata tab.

        Parameters
        ----------
        obj_name : str
            Name of iRODS collection or data object selected.
        path_name : str
            Name of path in which `obj_name` resides.

        """
        obj = None
        if self.ic.collection_exists(obj_path):
            obj = self.ic.get_collection(obj_path)
            content = ['Collections:', '-----------------']
            content.extend([sc.name for sc in obj.subcollections])
            content.extend(['\n', 'DataObjects:', '-----------------'])
            content.extend([do.name for do in obj.data_objects])
            preview_string = '\n'.join(content)
            self.widget.previewBrowser.append(preview_string)
        elif self.ic.dataobject_exists(obj_path):
            obj = self.ic.get_dataobject(obj_path)
            file_type = pathlib.Path(obj_path).suffix[1:]
            if file_type in ['txt', 'json', 'csv']:
                try:
                    with obj.open('r') as objfd:
                        preview_string = objfd.read(1024).decode('utf-8')
                    self.widget.previewBrowser.append(preview_string)
                except Exception as error:
                    self.widget.previewBrowser.append(
                        f'No Preview for: {obj_path}')
                    self.widget.previewBrowser.append(repr(error))
                    self.widget.previewBrowser.append(
                        "Storage resource might be down.")
            else:
                self.widget.previewBrowser.append(
                    f'No Preview for: {obj_path}')

    def _get_object_name_and_path(self, row):
        obj_name = self.widget.collTable.item(row, 1).text()
        if self.widget.collTable.item(row, 0).text() != '':
            path_name = self.widget.collTable.item(row, 0).text()
        else:
            path_name = self.widget.inputPath.text()
        return obj_name, path_name

    # @TODO: Add a proper data model for the table model
    def _get_irods_item_of_table_row(self, row):
        cell, parent = self._get_object_name_and_path(row)
        full_path = iRODSPath(parent, cell)
        # TODOD: this is a rather arbitrary mode of determining whether
        # object is a collection or data_object
        if cell.endswith("/"):
            item = self.ic.session.collections.get(full_path)
        else:
            item = self.ic.session.data_objects.get(full_path)

        return item

    def _get_selected_objects(self):
        rows = {row.row() for row in self.widget.collTable.selectedIndexes()}
        objects = []
        for row in rows:
            item = self._get_irods_item_of_table_row(row)
            objects.append(item)

        return objects

    def loadTable(self):
        # loads main browser table
        try:
            self._clear_error_label()
            self._clear_view_tabs()
            obj_path = iRODSPath(self.widget.inputPath.text())
            if self.ic.session.collections.exists(obj_path):
                coll = self.ic.session.collections.get(obj_path)
                self.widget.collTable.setRowCount(len(coll.data_objects)+len(coll.subcollections))
                row = 0
                for subcoll in coll.subcollections:
                    self.widget.collTable.setItem(row, 1, PyQt6.QtWidgets.QTableWidgetItem(subcoll.name+"/"))
                    self.widget.collTable.setItem(row, 2, PyQt6.QtWidgets.QTableWidgetItem(""))
                    self.widget.collTable.setItem(row, 3, PyQt6.QtWidgets.QTableWidgetItem(""))
                    self.widget.collTable.setItem(row, 0, PyQt6.QtWidgets.QTableWidgetItem(""))
                    row = row+1
                for obj in coll.data_objects:
                    self.widget.collTable.setItem(row, 1, PyQt6.QtWidgets.QTableWidgetItem(obj.name))
                    self.widget.collTable.setItem(
                        row, 2, PyQt6.QtWidgets.QTableWidgetItem(str(obj.size)))
                    self.widget.collTable.setItem(
                        row, 3, PyQt6.QtWidgets.QTableWidgetItem(str(obj.checksum)))
                    self.widget.collTable.setItem(
                        row, 4, PyQt6.QtWidgets.QTableWidgetItem(str(obj.modify_time)))
                    self.widget.collTable.setItem(row, 0, PyQt6.QtWidgets.QTableWidgetItem(""))
                    row = row+1
                self.widget.collTable.resizeColumnsToContents()
            else:
                self.widget.collTable.setRowCount(0)
                self.widget.errorLabel.setText("Collection does not exist.")
        except irods.exception.NetworkException:
            logging.exception("Something went wrong")
            self.widget.errorLabel.setText(
                    "IRODS NETWORK ERROR: No Connection, please check network")

    def resetPath(self):
        self.widget.inputPath.setText(self.root_coll.path)
    
    # @QtCore.pyqtSlot(QtCore.QModelIndex)
    def updatePath(self, index):
        self._clear_error_label()
        row = index.row()
        obj_name, parent = self._get_object_name_and_path(row)
        if obj_name.endswith("/"):  # collection
            self.widget.inputPath.setText(iRODSPath(parent, obj_name))

    # @QtCore.pyqtSlot(QtCore.QModelIndex)
    def fillInfo(self, index):
        self._clear_error_label()
        self._clear_view_tabs()

        self.widget.metadataTable.setRowCount(0)
        self.widget.aclTable.setRowCount(0)
        self.widget.resourceTable.setRowCount(0)
        
        row = index.row()
        self.currentBrowserRow = row
        obj_name, path_name = self._get_object_name_and_path(row)
        obj_path = iRODSPath(path_name, obj_name)
       
        self._clear_view_tabs()
        try:
            self._fill_preview_tab(obj_path)
            self._fill_metadata_tab(obj_path)
            self._fill_acls_tab(obj_path)
            self._fill_resources_tab(obj_path)
        except Exception as e:
            logging.info('ERROR in Browser',exc_info=True)
            self.widget.errorLabel.setText(repr(e))

    def loadSelection(self):
        # loads selection from main table into delete tab
        self.widget.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.WaitCursor))
        self.widget.deleteSelectionBrowser.clear()
        path_name = self.widget.inputPath.text()
        row = self.widget.collTable.currentRow()
        if row > -1:
            obj_name = self.widget.collTable.item(row, 1).text()
            obj_path = "/"+path_name.strip("/")+"/"+obj_name.strip("/")
            try:
                if self.ic.session.collections.exists(obj_path):
                    irodsDict = utils.utils.walkToDict(self.ic.session.collections.get(obj_path))
                elif self.ic.session.data_objects.exists(obj_path):
                    irodsDict = {self.ic.session.data_objects.get(obj_path).path: []}
                else:
                    self.widget.errorLabel.setText("Load: nothing selected.")
                    pass

                for key in list(irodsDict.keys())[:20]:
                    self.widget.deleteSelectionBrowser.append(key)
                    if len(irodsDict[key]) > 0:
                        for item in irodsDict[key]:
                            self.widget.deleteSelectionBrowser.append('\t'+item)
                self.widget.deleteSelectionBrowser.append('...')
            except irods.exception.NetworkException:
                self.widget.errorLabel.setText(
                    "IRODS NETWORK ERROR: No Connection, please check network")
                self.widget.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.ArrowCursor))
        self.widget.setCursor(PyQt6.QtGui.QCursor(PyQt6.QtCore.Qt.CursorShape.ArrowCursor))

    def deleteData(self):
        # Deletes all data in the deleteSelectionBrowser
        self.widget.errorLabel.clear()
        data = self.widget.deleteSelectionBrowser.toPlainText().split('\n')
        if data[0] != '':
            deleteItem = data[0].strip()
            quit_msg = "Delete all data in \n\n"+deleteItem+'\n'
            reply = PyQt6.QtWidgets.QMessageBox.question(
                self.widget, 'Message', quit_msg,
                PyQt6.QtWidgets.QMessageBox.StandardButton.Yes,
                PyQt6.QtWidgets.QMessageBox.StandardButton.No)
            if reply == PyQt6.QtWidgets.QMessageBox.StandardButton.Yes:
                try:
                    if self.ic.session.collections.exists(deleteItem):
                        item = self.ic.session.collections.get(deleteItem)
                    else:
                        item = self.ic.session.data_objects.get(deleteItem)
                    self.ic.deleteData(item)
                    self.widget.deleteSelectionBrowser.clear()
                    self.loadTable()
                    self.widget.errorLabel.clear()

                except Exception as error:
                    self.widget.errorLabel.setText("ERROR DELETE DATA: "+repr(error))

    def createCollection(self):
        parent = "/"+self.widget.inputPath.text().strip("/")
        creteCollWidget = gui.popupWidgets.irodsCreateCollection(parent, self.ic)
        creteCollWidget.exec()
        self.loadTable()

    def fileUpload(self):
        from utils.utils import getSize
        dialog = PyQt6.QtWidgets.QFileDialog(self.widget)
        fileSelect = PyQt6.QtWidgets.QFileDialog.getOpenFileName(self.widget,
                        "Open File", "","All Files (*);;Python Files (*.py)")
        size = getSize([fileSelect[0]])
        buttonReply = PyQt6.QtWidgets.QMessageBox.question(
            self.widget, 'Message Box', "Upload " + fileSelect[0],
            PyQt6.QtWidgets.QMessageBox.StandardButton.Yes | PyQt6.QtWidgets.QMessageBox.StandardButton.No,
            PyQt6.QtWidgets.QMessageBox.StandardButton.No)
        if buttonReply == PyQt6.QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                parentColl = self.ic.session.collections.get("/"+self.widget.inputPath.text().strip("/"))
                print("Upload "+fileSelect[0]+" to "+parentColl.path+" on resource "+self.ic.default_resc)
                self.ic.upload_data(fileSelect[0], parentColl,
                        None, size, force=self.force)
                self.loadTable()
            except irods.exception.NetworkException:
                self.widget.errorLabel.setText(
                    "IRODS NETWORK ERROR: No Connection, please check network")
            except Exception as error:
                print("ERROR upload :", fileSelect[0], "failed; \n\t", repr(error))
                self.widget.errorLabel.setText(repr(error))
                raise error
        else:
            pass

    def fileDownload(self):
        #If table is filled
        if self.widget.collTable.item(self.currentBrowserRow, 1) != None:
            objName = self.widget.collTable.item(self.currentBrowserRow, 1).text()
            if self.widget.collTable.item(self.currentBrowserRow, 0).text() == '':
                parent = self.widget.inputPath.text()
            else:
                parent = self.widget.collTable.item(self.currentBrowserRow, 0).text()
            try:
                if self.ic.session.data_objects.exists(parent+'/'+objName):
                    downloadDir = utils.utils.getDownloadDir()
                    buttonReply = PyQt6.QtWidgets.QMessageBox.question(self.widget,
                                'Message Box',
                                'Download\n'+parent+'/'+objName+'\tto\n'+downloadDir)
                    if buttonReply == PyQt6.QtWidgets.QMessageBox.StandardButton.Yes:
                        obj = self.ic.session.data_objects.get(parent+'/'+objName)
                        self.ic.download_data(obj, downloadDir, obj.size)
                        self.widget.errorLabel.setText("File downloaded to: "+downloadDir)
            except irods.exception.NetworkException:
                self.widget.errorLabel.setText(
                    "IRODS NETWORK ERROR: No Connection, please check network")
            except Exception as error:
                print("ERROR download :", parent+'/'+objName, "failed; \n\t", repr(error))
                self.widget.errorLabel.setText(repr(error))

    # @QtCore.pyqtSlot(QtCore.QModelIndex)
    def editMetadata(self, index):
        self._clear_error_label()
        self.widget.metaValueField.clear()
        self.widget.metaUnitsField.clear()
        row = index.row()
        key = self.widget.metadataTable.item(row, 0).text()
        value = self.widget.metadataTable.item(row, 1).text()
        units = self.widget.metadataTable.item(row, 2).text()
        self.widget.metaKeyField.setText(key)
        self.widget.metaValueField.setText(value)
        self.widget.metaUnitsField.setText(units)
        self.currentMetadata = (key, value, units)

    # @QtCore.pyqtSlot(QtCore.QModelIndex)
    def editACL(self, index):
        self._clear_error_label()
        self.widget.aclUserField.clear()
        self.widget.aclZoneField.clear()
        self.widget.aclBox.setCurrentText("----")
        row = index.row()
        user = self.widget.aclTable.item(row, 0).text()
        zone = self.widget.aclTable.item(row, 1).text()
        acl = self.widget.aclTable.item(row, 2).text()
        self.widget.aclUserField.setText(user)
        self.widget.aclZoneField.setText(zone)
        self.widget.aclBox.setCurrentText(acl)
        self.currentAcl = (user, acl)

    def updateIcatAcl(self):
        self.widget.errorLabel.clear()
        user = self.widget.aclUserField.text()
        rights = self.widget.aclBox.currentText()
        recursive = self.widget.recurseBox.currentText() == 'True'
        cell, parent = self._get_object_name_and_path(self.currentBrowserRow)
        obj_path  = iRODSPath(parent, cell) 
        zone = self.widget.aclZoneField.text()
        try:
            self.ic.set_permissions(rights, obj_path, user, zone, recursive)
            self._fill_acls_tab(obj_path)

        except irods.exception.NetworkException:
            self.widget.errorLabel.setText(
                    "IRODS NETWORK ERROR: No Connection, please check network")

        except Exception as error:
            self.widget.errorLabel.setText(repr(error))

    def updateIcatMeta(self):
        self.widget.errorLabel.clear()
        newKey = self.widget.metaKeyField.text()
        newVal = self.widget.metaValueField.text()
        newUnits = self.widget.metaUnitsField.text()
        try:
            if newKey != "" and newVal != "":
                item = self._get_irods_item_of_table_row(self.currentBrowserRow)
                
                self.ic.updateMetadata([item], newKey, newVal, newUnits)
                self._fill_metadata_tab(item.path)
                self._fill_resources_tab(item.path)
        except irods.exception.NetworkException:
            self.widget.errorLabel.setText("IRODS NETWORK ERROR: No Connection, please check network")

        except Exception as error:
            self.widget.errorLabel.setText(repr(error))

    def addIcatMeta(self):
        self.widget.errorLabel.clear()
        newKey = self.widget.metaKeyField.text()
        newVal = self.widget.metaValueField.text()
        newUnits = self.widget.metaUnitsField.text()
        if newKey != "" and newVal != "":
            try:
                item = self._get_irods_item_of_table_row(self.currentBrowserRow)
                self.ic.addMetadata([item], newKey, newVal, newUnits)
                self._fill_metadata_tab(item.path)
                self._fill_resources_tab(item.path)
            except irods.exception.NetworkException:
                self.widget.errorLabel.setText("IRODS NETWORK ERROR: No Connection, please check network")

            except Exception as error:
                self.widget.errorLabel.setText(repr(error))

    def deleteIcatMeta(self):
        self.widget.errorLabel.clear()
        key = self.widget.metaKeyField.text()
        val = self.widget.metaValueField.text()
        units = self.widget.metaUnitsField.text()
        try:
            if key != "" and val != "":
                item = self._get_irods_item_of_table_row(self.currentBrowserRow)
                self.ic.deleteMetadata([item], key, val, units)

                self._fill_metadata_tab(item.path)
        except irods.exception.NetworkException:
            self.widget.errorLabel.setText("IRODS NETWORK ERROR: No Connection, please check network")

        except Exception as error:
            self.widget.errorLabel.setText(repr(error))

    def loadMetadataFile(self):
        path, filter = PyQt6.QtWidgets.QFileDialog.getOpenFileName(
            None, 'Select file', '',
            'Metadata files (*.csv *.json *.xml);;All files (*)')
        if path:
            self.widget.errorLabel.clear()
            items = self._get_selected_objects()
            avus = meta.metadataFileParser.parse(path)
            if len(items) and len(avus):
                self.ic.addMultipleMetadata(items, avus)
                self._fill_metadata_tab(items[0].path)
