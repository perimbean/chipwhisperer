#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2014, NewAE Technology Inc
# All rights reserved.
#
# Author: Colin O'Flynn
#
# Find this and more at newae.com - this file is part of the chipwhisperer
# project, http://www.assembla.com/spaces/chipwhisperer
#
#    This file is part of chipwhisperer.
#
#    chipwhisperer is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    chipwhisperer is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with chipwhisperer.  If not, see <http://www.gnu.org/licenses/>.
#=================================================

import sys
import copy

try:
    from PySide.QtCore import *
    from PySide.QtGui import *
except ImportError:
    print "ERROR: PySide is required for this program"
    sys.exit()

import numpy as np
import random

from openadc.ExtendedParameter import ExtendedParameter
from pyqtgraph.parametertree import Parameter
from chipwhisperer.analyzer.attacks.models.AES128_8bit import getHW
from chipwhisperer.analyzer.attacks.models.AES128_8bit import INVSHIFT
from chipwhisperer.analyzer.models.aes.key_schedule import keyScheduleRounds
from chipwhisperer.analyzer.models.aes.funcs import sbox, inv_sbox

class PartitionHDLastRound(object):

    sectionName = "Partition Based on HD of Last Round"
    partitionType = "HD AES Last-Round"

    def getNumPartitions(self):
        return 9

    def getPartitionNum(self, trace, tnum):
        key = trace.getKnownKey(tnum)
        ct = trace.getTextout(tnum)

        #Convert from initial key to final-round key, currently
        #this assumes AES
        if len(key) == 16:
            rounds = 10
        else:
            raise ValueError("Need to implement for selected AES")
        key = keyScheduleRounds(key, 0, rounds)

        guess = [0] * 16
        for i in range(0, 16):
            st10 = ct[INVSHIFT[i]]
            st9 = inv_sbox(ct[i] ^ key[i])
            guess[i] = getHW(st9 ^ st10)
        return guess

class PartitionHWIntermediate(object):

    sectionName = "Partition Based on HW of Intermediate"
    partitionType = "HW AES Intermediate"

    def getNumPartitions(self):
        return 9

    def getPartitionNum(self, trace, tnum):
        key = trace.getKnownKey(tnum)
        text = trace.getTextin(tnum)

        guess = [0] * 16
        for i in range(0, 16):
            guess[i] = getHW(sbox(text[i] ^ key[i]))

        return guess

class PartitionEncKey(object):

    sectionName = "Partition Based on Key Value"
    partitionType = "Key Value"

    def getNumPartitions(self):
        return 256

    def getPartitionNum(self, trace, tnum):
        key = trace.getKnownKey(tnum)
        return key

class PartitionRandvsFixed(object):

    sectionName = "Partition Based on Rand vs Fixed "
    partitionType = "Rand vs Fixed"

    def getNumPartitions(self):
        return 2

    def getPartitionNum(self, trace, tnum):
        return [tnum % 2]

class PartitionRandDebug(object):

    sectionName = "Partition Randomly (debug)"
    partitionType = "Randomly (debug)"

    numRand = 2

    def getNumPartitions(self):
        return self.numRand

    def getPartitionNum(self, trace, tnum):
        return [random.randint(0, self.numRand - 1)]

class PartitionDialog(QDialog):
    """Open dialog to run partioning"""

    def __init__(self, parent, partInst):
        super(PartitionDialog, self).__init__(parent)

        self.part = partInst

        self.setWindowTitle("Partition Traces")
        self.setObjectName("Partition Traces")

        layoutPart = QHBoxLayout()

        pbStart = QPushButton("Generate Partitions")
        pbStart.clicked.connect(self.runGenerate)
        layoutPart.addWidget(pbStart)
        self.setLayout(layoutPart)

    def runGenerate(self):
        pb = QProgressBar(self)

        # TODO: Partition generation doesn't work
        pb.setMinimum(0)
        pb.setMinimum(self.part.trace.numTrace())

        self.part.runPartitions(report=pb.setValue)

class Partition(QObject):
    """
    Base Class for all partioning modules
    """
    paramListUpdated = Signal(list)
    # traceDone = Signal(int)

    descrString = "Partition traces based on some method"

    attrDictPartition = {
                "sectionName":"Partition Based on XXXX",
                "moduleName":"Partitions",
                "module":None,
                "values":{
                    "round":{"value":0, "desc":"Round", "changed":False, "definesunique":True},
                    "filename":{"value":None, "desc":"Partition File", "changed":False, "headerLabel":"Partition Data"},
                    },
                }

    supportedMethods = [PartitionRandvsFixed, PartitionEncKey, PartitionRandDebug, PartitionHWIntermediate, PartitionHDLastRound]

    def __init__(self, parent, console=None, showScriptParameter=None):
        """Pass None/None if you don't have/want console/showScriptParameter"""
        super(Partition, self).__init__()
        self.console = console
        self.showScriptParameter = showScriptParameter
        self.parent = parent
        self._tmanager = None
        if parent is not None:
            self.setTraceManager(parent.traceManager())
        self.setupParameters()
        self.partDataCache = None

    def setupParameters(self):
        """Setup parameters specific to preprocessing module"""
        # ssParams = [{'name':'Enabled', 'type':'bool', 'value':True, 'set':self.setEnabled},
        #            # PUT YOUR PARAMETERS HERE
        #            {'name':'Desc', 'type':'text', 'value':self.descrString}]
        # self.params = Parameter.create(name='Name of Module', type='group', children=ssParams)
        # ExtendedParameter.setupExtended(self.params, self)

        self.setPartMethod(PartitionRandvsFixed)

    def setPartMethod(self, method):
        self.partMethodClass = method
        self.partMethod = method()
        self.attrDictPartition["sectionName"] = self.partMethod.sectionName
        self.attrDictPartition["moduleName"] = self.partMethod.__class__.__name__

    def paramList(self):
        """Returns the parameter list"""
        return [self.params]

    def init(self):
        """Do any initilization required once all traces are loaded"""
        pass

    def setTraceManager(self, tmanager):
        """Set the input trace source"""
        self._tmanager = tmanager

    def traceManager(self):
        if self._tmanager is None and self.parent is not None:
            self._tmanager = self.parent.traceManager()
        return self._tmanager

    def createBlankTable(self, t):
        # Create storage for partition information
        partitionTable = []
        #for j in range(0, len(t.getKnownKey())):
        for j in range(0, len(self.partMethod.getPartitionNum(t, 0))):
            partitionTable.append([])
            for i in range(0, self.partMethod.getNumPartitions()):
                partitionTable[j].append([])

        return partitionTable

    def loadPartitions(self, tRange=(0, -1)):
        """Load partitions from trace files, convert to mapped range"""

        start = tRange[0]
        end = tRange[1]

        if end == -1:
            end = self.traceManager().numTrace()

        # Generate blank partition table
        partitionTable = self.createBlankTable(self.traceManager().findMappedTrace(start))
        print np.shape(partitionTable)

        tnum = start
        while tnum < end:
            t = self.traceManager().findMappedTrace(tnum)
            # Discover where this trace starts & ends
            tmapstart = t.mappedRange[0]
            tmapend = t.mappedRange[1]
            tmapend = min(tmapend, end)

            partcfg = t.getAuxDataConfig(self.attrDictPartition)
            # print partcfg
            # print partcfg["filename"]
            partdata = t.loadAuxData(partcfg["filename"])

            # Merge tables now - better way to do this?
            for j in range(0, len(self.partMethod.getPartitionNum(t, 0))):
                for i in range(0, self.partMethod.getNumPartitions()):
                    partitionTable[j][i] = partitionTable[j][i] + partdata[j][i]

            # print tmapstart

            # Next trace round
            tnum = tmapend + 1

        return partitionTable

    def getPartitionData(self):
        return self.partDataCache

    def generatePartitions(self, partitionClass=None, saveFile=False, loadFile=False, traces=None, tRange=(0, -1)):
        """
        Generate partitions, using previously setup setTraceManager & partition class, or if they are passed as
        arguments will update the class data
        """

        if traces:
            self.setTraceManager(traces)

        if partitionClass:
            self.setPartMethod(partitionClass)

        partitionTable = None

        if loadFile:
            partitionTable = self.loadPartitions(tRange)

        start = tRange[0]
        end = tRange[1]

        if partitionTable is None:
            partitionTable = self.createBlankTable(self.traceManager().findMappedTrace(start))

            if end == -1:
                end = self.traceManager().numTrace()

            tnum = start
            while tnum < end:
                t = self.traceManager().findMappedTrace(tnum)
                # Discover where this trace starts & ends
                tmapstart = t.mappedRange[0]
                tmapend = t.mappedRange[1]

                for tnum in range(tmapstart, tmapend + 1):
                    # Check each trace, write partition number
                    partNum = self.partMethod.getPartitionNum(t, tnum - tmapstart)
                    for i, pn in enumerate(partNum):
                        partitionTable[i][pn].append(tnum - tmapstart)

                    # self.traceDone.emit(tnum)

                if saveFile:
                    # Save partition table, reference it in config file
                    newCfgDict = copy.deepcopy(self.attrDictPartition)
                    updatedDict = t.addAuxDataConfig(newCfgDict)
                    t.saveAuxData(partitionTable, updatedDict)

                # Debug - Dump Table
                # for t in range(0, self.partMethod.getNumPartitions()):
                #    print "Traces in %d:" % t
                #    print "  ",
                #    print partitionTable[0][t]

                tnum = tmapend + 1

        self.partDataCache = partitionTable
        return partitionTable
