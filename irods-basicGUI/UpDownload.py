from PyQt5.QtWidgets import QMainWindow, QHeaderView, QMessageBox
import logging
import os

from checkableFsTree import checkableFsTreeModel
from irodsTreeView  import IrodsModel
from utils import getSize, saveIenv
from continousUpload import contUpload

from irodsCreateCollection import irodsCreateCollection
from createDirectory import createDirectory
from UpDownloadCheck import UpDownloadCheck

class irodsUpDownload():
    def __init__(self, widget, ic, ienv):
        self.ic = ic
        self.widget = widget
        self.ienv = ienv
        self.syncing = False # syncing or not

        # QTreeViews
        self.dirmodel = checkableFsTreeModel(self.widget.localFsTreeView)
        self.widget.localFsTreeView.setModel(self.dirmodel)
        # Hide all columns except the Name
        self.widget.localFsTreeView.setColumnHidden(1, True)
        self.widget.localFsTreeView.setColumnHidden(2, True)
        self.widget.localFsTreeView.setColumnHidden(3, True)
        self.widget.localFsTreeView.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.dirmodel.initial_expand()
        
         # iRODS  zone info
        self.widget.irodsZoneLabel.setText("/"+self.ic.session.zone+":")
        # iRODS tree
        self.irodsmodel = IrodsModel(ic, self.widget.irodsFsTreeView)
        self.widget.irodsFsTreeView.setModel(self.irodsmodel)
        self.irodsRootColl = '/'+ic.session.zone
       
        #self.widget.irodsFsTreeView.expanded.connect(self.irodsmodel.expanded)
        #self.widget.irodsFsTreeView.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        #self.irodsmodel.initial_expand()
        self.irodsmodel.setHorizontalHeaderLabels([self.irodsRootColl,
                                              'Level', 'iRODS ID',
                                              'parent ID', 'type'])

        self.widget.irodsFsTreeView.expanded.connect(self.irodsmodel.refreshSubTree)
        self.widget.irodsFsTreeView.clicked.connect(self.irodsmodel.refreshSubTree)
        self.irodsmodel.initTree()

        self.widget.irodsFsTreeView.setHeaderHidden(True)
        self.widget.irodsFsTreeView.header().setDefaultSectionSize(180)
        self.widget.irodsFsTreeView.setColumnHidden(1, True)
        self.widget.irodsFsTreeView.setColumnHidden(2, True)
        self.widget.irodsFsTreeView.setColumnHidden(3, True)
        self.widget.irodsFsTreeView.setColumnHidden(4, True)


        # Buttons
        self.widget.UploadButton.clicked.connect(self.upload)
        self.widget.DownloadButton.clicked.connect(self.download)
        self.widget.ContUplBut.clicked.connect(self.cont_upload)
        self.widget.ChecksumCheckBut.clicked.connect(self.check_checksum)
        self.widget.createFolderButton.clicked.connect(self.createFolder)
        self.widget.createCollButton.clicked.connect(self.createCollection)

        # Resource selector
        available_resources = self.ic.listResources()
        self.widget.resourceBox.clear()
        self.widget.resourceBox.addItems(available_resources)
        if ("ui_resource" in ienv) and (ienv["ui_resource"] != "") and (ienv["ui_resource"] in available_resources):
            index = self.widget.resourceBox.findText(ienv["ui_resource"])
            self.widget.resourceBox.setCurrentIndex(index)
        elif ("default_resource_name" in ienv) and (ienv["default_resource_name"] != "") and (ienv["default_resource_name"] in available_resources):
            index = self.widget.resourceBox.findText(ienv["default_resource_name"])
            self.widget.resourceBox.setCurrentIndex(index)
        self.widget.resourceBox.currentIndexChanged.connect(self.saveUIset)

        # Continious upload settings
        if ("ui_remLocalcopy" in ienv):
            self.widget.rLocalcopyCB.setChecked(ienv["ui_remLocalcopy"])
        if ("ui_uplMode" in ienv):
            uplMode =  ienv["ui_uplMode"]
            if uplMode == "f500":
                self.widget.uplF500RB.setChecked(True)
            elif uplMode == "meta":
                self.widget.uplMetaRB.setChecked(True)
            else:
                self.widget.uplAllRB.setChecked(True)
        self.widget.rLocalcopyCB.stateChanged.connect(self.saveUIset)
        self.widget.uplF500RB.toggled.connect(self.saveUIset)
        self.widget.uplMetaRB.toggled.connect(self.saveUIset)
        self.widget.uplAllRB.toggled.connect(self.saveUIset)

    def saveUIset(self):
        self.ienv["ui_resource"] = self.getResource()
        self.ienv["ui_remLocalcopy"] = self.getRemLocalCopy()
        self.ienv["ui_uplMode"] = self.getUplMode()
        saveIenv(self.ienv)


    def getResource(self):
        return self.widget.resourceBox.currentText()

    def getRemLocalCopy(self):
        return self.widget.rLocalcopyCB.isChecked()

    def getUplMode(self):
        if self.widget.uplF500RB.isChecked():
            uplMode = "f500"
        elif self.widget.uplMetaRB.isChecked():
            uplMode = "meta"
        else: # Default
            uplMode = "all"
        return uplMode


    # Check checksums to confirm the upload
    def check_checksum(self):
        print("TODO, or maybe skipp?")


    def createFolder(self):
        parent = self.dirmodel.get_checked()
        if parent != None:
            createDirWidget = createDirectory(parent)
            createDirWidget.exec_()
            #self.dirmodel.initial_expand(previous_item = parent)


    def createCollection(self):
        idx, parent = self.irodsmodel.get_checked()
        creteCollWidget = irodsCreateCollection(parent, self.ic)
        creteCollWidget.exec_()
        self.irodsmodel.refreshSubTree(idx)


    # Upload a file/folder to IRODS and refresh the TreeView
    def upload(self):
        (source, destInd, destPath) = self.upload_get_paths()
        if source == None: 
            return           
        destColl = self.ic.session.collections.get(destPath)
        if os.path.isdir(source):
            self.uploadWindow = UpDownloadCheck(self.ic, True, source, destColl, destInd, self.getResource())
            self.uploadWindow.finished.connect(self.finishedUpDownload)
        else: # File
            try:
                self.ic.uploadData(source, destColl, self.getResource(), getSize(source), buff = 1024**3)# TODO keep 500GB free to avoid locking irods!
                QMessageBox.information(self.widget, "status", "File uploaded.")
            except Exception as error:
                logging.info(repr(error))
                QMessageBox.information(self.widget, "status", "Something went wrong.")

    def finishedUpDownload(self, succes, destInd):# slot for uploadcheck
        if succes == True:
            self.irodsmodel.refreshSubTree(destInd)
        self.uploadWindow = None # Release


    # Download a file/folder from IRODS to local disk
    def download(self):
        source_ind, source_path = self.irodsmodel.get_checked()
        if source_ind == None:
            message = "No file/folder selected for download"
            QMessageBox.information(self.widget, 'Error', message)
            #logging.info("Filedownload:" + message)
            return
        destination = self.dirmodel.get_checked()
        if destination == None:
            message = "No Folder selected to download to"
            QMessageBox.information(self.widget, 'Error', message)
            #logging.info("Fileupload:" + message)
            return
        elif not os.path.isdir(destination):
            message = "Can only download to folders, not files."
            QMessageBox.information(self.widget, 'Error', message)
            #logging.info("Fileupload:" + message)
            return
        elif not os.access(destination, os.R_OK):
            message = "No write permission on current folder"
            QMessageBox.information(self.widget, 'Error', message)
            return 
        # File           
        if self.ic.session.data_objects.exists(source_path):
            try:
                sourceObj = self.ic.session.data_objects.get(source_path)
                self.ic.downloadData(sourceObj, destination)
                QMessageBox.information(self.widget, "status", "File downloaded.")
            except Exception as error:
                logging.info(repr(error))
                QMessageBox.information(self.widget, "status", "Something went wrong.")
        else:
            sourceColl = self.ic.session.collections.get(source_path)
            self.uploadWindow = UpDownloadCheck(self.ic, False, destination, sourceColl)
            self.uploadWindow.finished.connect(self.finishedUpDownload)


    # Continous file upload
    def cont_upload(self):
        (source, destInd, destPath) = self.upload_get_paths()
        if source == None: 
            return
        if self.syncing == False:
            self.syncing = True
            self.widget.ContUplBut.setStyleSheet("image : url(icons/syncing.png) stretch stretch;")
            self.en_disable_controls(False)
            upl_mode = self.get_upl_mode()
            r_local_copy = self.widget.rLocalcopyCB.isChecked()
            destColl = self.ic.session.collections.get(destPath)
            self.uploader = contUpload(self.ic, source, destColl, upl_mode, r_local_copy)
            #self.uploader.start()
        else:
            #self.uploader.stop()
            self.syncing = False
            self.widget.ContUplBut.setStyleSheet("image : url(icons/nosync.png) stretch stretch;")
            self.en_disable_controls(True)


    def en_disable_controls(self, enable):
        # Loop over all tabs enabling/disabling them
        for i in range(0, self.widget.tabWidget.count()):
            t = self.widget.tabWidget.tabText(i)
            if self.widget.tabWidget.tabText(i) == "Up and Download":
                continue
            self.widget.tabWidget.setTabVisible(i, enable)
        self.widget.UploadButton.setEnabled(enable)
        self.widget.DownloadButton.setEnabled(enable)
        self.widget.uplSetGB.setEnabled(enable)


    # Helpers to check file paths before upload
    def upload_get_paths(self):
        source = self.dirmodel.get_checked()
        if self.upload_check_source(source) == False:
            return (None, None, None)     
        dest_ind, dest_path = self.irodsmodel.get_checked()
        if self.upload_check_dest(dest_ind, dest_path) == False:
            return (None, None, None)     
        return (source, dest_ind, dest_path)


    def upload_check_source(self, source):
        if source == None:
            message = "No file selected to upload"
            QMessageBox.information(self.widget, 'Error', message)
            #logging.info("Fileupload:" + message)
            return False


    def upload_check_dest(self, dest_ind, dest_collection):
        if dest_ind == None:
            message = "No collection selected to upload to"
            QMessageBox.information(self.widget, 'Error', message)
            #logging.info("Fileupload:" + message)
            return False
        elif dest_collection.find(".") != -1:
            message = "Can only upload to collections, not objects."
            QMessageBox.information(self.widget, 'Error', message)
            #logging.info("Fileupload:" + message)
            return False