#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2013-2014, NewAE Technology Inc
# All rights reserved.
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
import serial

from PySide.QtCore import *
from PySide.QtGui import *

import time

try:
    # OrderedDict is new in 2.7
    from collections import OrderedDict
    dicttype = OrderedDict
except ImportError:
    dicttype = dict

try:
    from pyqtgraph.parametertree import Parameter, ParameterTree, ParameterItem, registerParameterType
except ImportError:
    print "ERROR: PyQtGraph is required for this program"
    sys.exit()
    
from openadc.ExtendedParameter import ExtendedParameter
import chipwhisperer.capture.targets.ChipWhispererTargets as ChipWhispererTargets
import chipwhisperer.capture.targets.SimpleSerial as SimpleSerial
import chipwhisperer.capture.global_mod as global_mod
from TargetTemplate import TargetTemplate

class ReaderTemplate(QObject):
    paramListUpdated = Signal(list)
    
    def __init__(self, console, showScriptParameter):
        """Pass None/None if you don't have/want console/showScriptParameter"""
        super(ReaderTemplate, self).__init__()        
        self.console = console
        self.showScriptParameter = showScriptParameter                
        self.setupParameters()
        
    def log(self, message):
        if self.console:
            self.console.append(message)
        else:
            print message
                
    def setupParameters(self):
        """You should overload this. Copy/Paste into your class."""
        ssParams = [{'name':'Example Parameter', 'type':'int', 'value':5, 'set':self.setSomething}]        
        self.params = Parameter.create(name='Smartcard Reader', type='group', children=ssParams)
        ExtendedParameter.setupExtended(self.params, self)      
            
    def paramList(self):
        p = [self.params]
        #if self.ser is not None:
        #    for a in self.ser.paramList(): p.append(a)
        return p        
        
    def setSomething(self):
        """Here you would send value to the reader hardware"""
        pass 

    def sendAPDU(self):
        """Send APDU to SmartCard, get Response"""
        pass
    
    def con(self, oa=None):
        """Connect to reader. oa parameter is OpenADC/ChipWhisperer hardware, only used to integrated readers"""
        pass
    
    def flush(self):
        """Discard all input buffers"""
        pass
    
    def reset(self):
        """Reset card & save the ATR"""
        pass
    
    def getATR(self):
        """Get the ATR from the SmartCard. Reads a saved value, user reset() to actually reset card."""
        pass


class ReaderChipWhispererSER(ReaderTemplate):
    
    def __init__(self, console=None, showScriptParameter=None):
        super(ReaderChipWhispererSER, self).__init__(console, showScriptParameter)        
        
    def setupParameters(self):
        self.ser = SimpleSerial.SimpleSerial_ChipWhisperer(showScriptParameter=self.showScriptParameter)
        self.ser.setupParameters()              
        self.params = self.ser.params
        self.params.addChildren([{'name':'Reset Pin', 'type':'list', 'values':['GPIO1']},
                                {'name':'Get ATR (Reset Card)', 'type':'action', 'action':self.reset},
                                {'name':'ATR', 'key':'atr', 'type':'str'}                                
                                ])
        #ExtendedParameter.setupExtended(self.params, self)       
        
    def waitEcho(self, data):
        rxdata = []
        while len(rxdata) < len(data):
            char = self.ser.read(1)
            if len(char) == 0:
                print "SCARD TIMEOUT: Failed to echo data?"
                print "  SENT: %s"%" ".join(["%02x"%t for t in data])
                print "  RECEIVED: %s"%" ".join(["%02x"%ord(t) for t in rxdata])
                raise IOError("SmartCard Line Stuck?")
            rxdata.extend(char)
            
        #print "  SENT: %s"%" ".join(["%02x"%t for t in data])
        #print "  RECEIVED: %s"%" ".join(["%02x"%ord(t) for t in rxdata])
    
    def sendAPDU(self, cla, ins, p1, p2, txdata=None, rxdatalen=0):
        """Send APDU to SmartCard, get Response""" 
    
        #SmartCard header
        data = [cla,ins, p1, p2]
        
        #Flush input
        self.ser.flush()
        
        if txdata is not None:
            txdatalen = len(txdata)
            data.append(txdatalen)
        else:
            txdatalen = 0            
            data.append(rxdatalen)
                
        #Send data        
        self.ser.write(data)
        self.waitEcho(data)           
       
        #Wait for ACK - don't fail yet as some scards
        #don't send ACK properly it seems (mainly DPA Contest v4)
        ack = self.ser.read(1)
        
        #Send payload
        if txdata and len(txdata) > 0:
            self.ser.write(txdata)
            self.waitEcho(txdata)
            
        #Send length request if we had data
        if txdatalen > 0 and rxdatalen > 0:
            self.ser.write([rxdatalen])
            self.ser.read(1)        

        #Read Payload data
        rxdata = []
        while len(rxdata) < rxdatalen:
            char = self.ser.read(1)
            if len(char) == 0:
                break
            rxdata.extend(char)
            
        #Convert
        rxdata = [ord(t) for t in rxdata]
            
        #Read two bytes of status
        stat = self.ser.read(2)
                  
        # Uncomment to print data stream on RX pin
        #print "APDU: ",
        #for t in rxdata: print "%02x " % t,
        #print ""            
            
        if len(ack) < 1:
            print "ACK Error: not received?" 
        elif ord(ack[0]) != ins:
            print "ACK Error: %x != %x"%(ins, ord(ack[0]))
                        
        if len(stat) < 2:
            raise IOError("Status too small: %d, %s" % (len(stat), " ".join(["%02x"%ord(t) for t in stat])))
            
        status = (ord(stat[0]) << 8) | ord(stat[1])
        
        if rxdatalen > 0:
            payload = rxdata
            return (status, payload)
        
        return status
    
    def con(self, oa=None):
        """Connect to reader. oa parameter is OpenADC/ChipWhisperer hardware, only used to integrated readers"""
        self.ser.setOpenADC(oa)
        self.ser.con()
        
        #Set defaults
        self.ser.findParam('parity').setValue('e')
        
        #NB: This should be '2' I thought, but the turn-around time on the SASEBO-W card is too fast, so
        #    this needs to be reduced to '1' to avoid a collision.
        self.ser.findParam('stopbits').setValue(1)
        
        self.ser.findParam('rxbaud').setValue(9600)
        self.ser.findParam('txbaud').setValue(9600)
        
        #Setup GPIO Pins
        if hasattr(global_mod.active_scope, 'advancedSettings') and global_mod.active_scope.advancedSettings:
            self.cwe = global_mod.active_scope.advancedSettings
            self.cwe.findParam('gpio1mode').setValue(self.cwe.cwEXTRA.IOROUTE_GPIOE)
            self.cwe.findParam('gpio2mode').setValue(self.cwe.cwEXTRA.IOROUTE_HIGHZ)
            self.cwe.findParam('gpio3mode').setValue(self.cwe.cwEXTRA.IOROUTE_STXRX)
            self.cwe.findParam('gpiostate1').setValue(True)
        else:
            self.cwe = None
        
        self.reset()
    
    def flush(self):
        """Discard all input buffers"""
        self.ser.flush()
    
    def reset(self):
        """Reset card & save the ATR"""
        
        self.atr = [0]
        self.ser.findParam('atr').setValue("--atr not read--")
        
        if self.cwe is None:            
            return
        
        #Toggle GPIO1
        self.cwe.cwEXTRA.setGPIOState(False, 0)
        #Flush serial port
        self.ser.flush()
        time.sleep(0.01)
        self.cwe.cwEXTRA.setGPIOState(True, 0)
         
        #Read ATR
        atr = []
        rxdata = [0,0,0]
        while len(rxdata) > 0:
            rxdata = self.ser.read(1, 200)
            atr.extend(rxdata)
            
        self.atr = [ord(t) for t in atr]
        
        stratr = " ".join(["%02x"%ord(t) for t in atr])
        print "ATR: %s"%stratr
        self.ser.findParam('atr').setValue(stratr)        
    
    def getATR(self):
        """Get the ATR from the SmartCard. Reads a saved value, user reset() to actually reset card."""
        return self.atr


class ReaderChipWhispererUSI(ReaderTemplate):
    
    def __init__(self, console=None, showScriptParameter=None):
        super(ReaderChipWhispererUSI, self).__init__(console, showScriptParameter)
        self.usi = ChipWhispererTargets.CWUniversalSerial()
        

    def setupParameters(self):
        ssParams = [{'name':'Baud', 'type':'int', 'value':9600, 'set':self.setBaud}                                                            
                    ]        
        self.params = Parameter.create(name='Target Connection', type='group', children=ssParams)
        ExtendedParameter.setupExtended(self.params, self)       

    def setBaud(self, brate):
        """Set baud rate of reader"""
        
        #For SmartCard we assume Stop-bits = 1, guard-bits=1, start-bits=1, parity=even
        self.usi.setBaud(brate)
        
    
    def sendAPDU(self, cla, ins, p1, p2, txdata=None, rxdatalen=0):
        """Send APDU to SmartCard, get Response"""        
    
        #SmartCard header
        data = [cla,ins, p1, p2]
        
        if txdata is not None:
            txdatalen = len(txdata)
            data.append(txdatalen)
        else:
            txdatalen = 0
            
        if (txdata is None) & (rxdatalen == 0):
            data.append(0)
        
        #Append gap during which SCard sends ACK
        data.append(None)
        
        #Append payload
        if txdata is not None:
            for b in txdata: data.append(b)
            
        if rxdatalen != 0:
            data.append(rxdatalen)
        
        #Append requested response size
    
        #Additional processing time
        proctime = 8
    
        #Start RX to catch response
        self.usi.read(2+rxdatalen+txdatalen+proctime, startonly=True)
        self.usi.write(data)
        temprx = bytearray(self.usi.read(2 + rxdatalen + txdatalen + proctime, waitonly=True))

        # Uncomment to print data stream on RX pin
        print "APDU: ",
        for t in temprx: print "%02x " % t,
        print ""

        # We've actually read entire sent + received data in
        # Strip header
        del temprx[0:5]

        # Strip transmitted data
        if txdatalen > 0:
            del temprx[1:(txdatalen + 1)]

        # Strip receive data length, present only if TX + RX happened
        if rxdatalen > 0 and txdatalen > 0:
            del temprx[1]

        p = temprx
        
        if p[0] != ins:
            self.log("ACK Error: %x != %x"%(ins, p[0]))
            
        #for t in p:
        #    print "%x "%t,
            
        if len(p) < 2:
            raise IOError("Payload too small: %d, %s" % (len(p), str(p)))
            
        status = (p[-2] << 8) | p[-1]
        
        if rxdatalen > 0:
            payload = p[1:-2]
            return (status, payload)
        
        return status
    
    def con(self, oa=None):
        """Connect to reader. oa parameter is OpenADC/ChipWhisperer hardware, only used to integrated readers"""
        self.usi.con(oa)
        self.usi.setIdle(1)
        self.setBaud(9600)
        self.usi.setParity("even")        
        self.usi.setStopbits(2)
    
    def flush(self):
        """Discard all input buffers"""
        pass
    
    def reset(self):
        """Reset card & save the ATR"""
        pass
    
    def getATR(self):
        """Get the ATR from the SmartCard. Reads a saved value, user reset() to actually reset card."""
        pass
    
class ReaderChipWhispererSCard(ReaderTemplate):
    def __init__(self, console=None, showScriptParameter=None):
        super(ReaderChipWhispererSCard, self).__init__(console, showScriptParameter)
        self.scard = ChipWhispererTargets.CWSCardIntegrated()
        

    def setupParameters(self):
        ssParams = [{'name':'Card Present', 'key':'statusStr', 'type':'bool', 'value':False, 'readonly':True},
                    {'name':'Update Status', 'type':'action', 'action':self.statusUpdate},
                    {'name':'Answer To Reset (ATR)', 'key':'atr', 'type':'str', 'value':'', 'readonly':True},
                    {'name':'Reset Card', 'type':'action', 'action':self.reset},                                                        
                    ]        
        self.params = Parameter.create(name='Target Connection', type='group', children=ssParams)
        ExtendedParameter.setupExtended(self.params, self)       

    def reset(self):
        atr = self.scard.reset()
        self.findParam('atr').setValue(atr)
        
    def getATR(self):
        return self.scard.stratr

    def statusUpdate(self):
        self.findParam('statusStr').setValue(self.scard.isPresent())
        
    def con(self, oa):
        self.scard.con(oa)
        self.reset()

    def sendAPDU(self, cla, ins, p1, p2, txdata=None, rxdatalen=0):
        """Send APDU to SmartCard, get Response"""        
    
        if txdata is None:
            resp = self.scard.APDURecv(cla, ins, p1, p2, rxdatalen)
            status = resp[16:18]
            status = (status[0] << 8) | status[1]
            payload = resp[0:rxdatalen]
            
            print "%4x"%status
            
            return (status, payload)
   
        else:    
            return self.scard.APDUSend(cla, ins, p1, p2, txdata)


try:
    from smartcard.CardType import AnyCardType
    from smartcard.CardRequest import CardRequest
    from smartcard.CardConnection import CardConnection
    from smartcard.util import toHexString
except ImportError:
    AnyCardType = None
    
class ReaderPCSC(ReaderTemplate):    

    def __init__(self, console=None, showScriptParameter=None):
        super(ReaderPCSC, self).__init__(console, showScriptParameter)
        
        if AnyCardType is None:
            raise ImportError("smartcard libraries missing")           

    def setupParameters(self):
        ssParams = [{'name':'Keep-Alive Interval (off=0)', 'type':'int', 'value':2, 'set':self.setKeepalive}                                                            
                    ]        
        self.params = Parameter.create(name='Target Connection', type='group', children=ssParams)
        ExtendedParameter.setupExtended(self.params, self)    
        
        
        self.timeoutTimer = QTimer()  
        self.timeoutTimer.timeout.connect(self.timeoutFired)
        self.timeoutTimer.setInterval(2000)

    def setKeepalive(self, kinterval):
        self.timeoutTimer.setInterval(kinterval*1000)
    
    def timeoutFired(self):
        self.scserv.connection.connect()       
    
    def sendAPDU(self, cla, ins, p1, p2, txdata=None, rxdatalen=0):
        """Send APDU to SmartCard, get Response"""       

        data = [cla,ins, p1, p2]
        
        if txdata is not None:
            txdatalen = len(txdata)
            data.append(txdatalen)
        else:
            txdatalen = 0
            
        if (txdata is None) & (rxdatalen == 0):
            data.append(0)
                
        #Append payload
        if txdata is not None:
            for b in txdata: data.append(b)
            
        if rxdatalen != 0:
            data.append(rxdatalen)
        
        response, sw1, sw2 = self.scserv.connection.transmit(data , CardConnection.T1_protocol)
            
        status = (sw1 << 8) | sw2;
        
        if rxdatalen > 0:
            return (status, response)
        
        return status
    
    def con(self, oa=None):
        """Connect to reader. oa parameter is OpenADC/ChipWhisperer hardware, only used to integrated readers"""
        try:
            self.sccard = AnyCardType()
            self.screq = CardRequest(timeout=1, cardType=self.sccard)
            self.scserv = self.screq.waitforcard()

            #observer = ConsoleCardConnectionObserver()
            #self.scserv.connection.addObserver( observer )           
            
            if not self.timeoutTimer.isActive():
                self.timeoutTimer.start()

        except CardRequestTimeoutException:
            return False

        return True        
    
    def flush(self):
        """Discard all input buffers"""
        pass
    
    def reset(self):
        """Reset card & save the ATR"""
        pass
    
    def getATR(self):
        """Get the ATR from the SmartCard. Reads a saved value, user reset() to actually reset card."""
        pass
    
    def dis(self):
        self.scserv.connection.disconnect()
        self.timeoutTimer.stop()
    
class ProtocolTemplate(QObject):
    paramListUpdated = Signal(list)
    
    def __init__(self, console=None, showScriptParameter=None):
        super(ProtocolTemplate, self).__init__()
        
        self.console = console
        self.showScriptParameter = showScriptParameter
        self.hw = None
        self.setupParameters()
        
    def log(self, message):
        self.console.append(message)
                
    def setupParameters(self):
        """You should overload this. Copy/Paste into your class."""
        ssParams = [{'name':'Example Parameter', 'type':'int', 'value':5, 'set':self.setSomething}]        
        self.params = Parameter.create(name='Smartcard Reader', type='group', children=ssParams)
        ExtendedParameter.setupExtended(self.params, self)      
            
    def paramList(self):
        p = [self.params]
        #if self.ser is not None:
        #    for a in self.ser.paramList(): p.append(a)
        return p    

    def setReaderHardware(self, hw):
        self.hw = hw
    
    def init(self):
        pass

    def reinit(self):
        pass
    
    def loadEncryptionKey(self, key):
        pass
      
    def loadInput(self, inputtext):
        self.input = inputtext

    def isDone(self):
        return True

    def readOutput(self):        
        return ""

    def go(self):
        pass
    
class ProtocolSASEBOWCardOS(ProtocolTemplate):

    def setupParameters(self):
        """No parameters"""
        #ssParams = []        
        #self.params = Parameter.create(name='Smartcard Reader', type='group', children=ssParams)
        #ExtendedParameter.setupExtended(self.params, self)
        self.params = None
        
    def loadEncryptionKey(self, key):
        if len(key) != 16:
            raise ValueError("Encryption key != 16 bytes??")
        status = self.hw.sendAPDU(0x80, 0x12, 0x00, 0x00, key)
        self.key = key
        #print status
        
    def loadInput(self, inputtext):
        self.input = inputtext
        
    def go(self):
        if len(self.input) != 16:
            raise ValueError("Plaintext != 16 bytes??")
        status = self.hw.sendAPDU(0x80, 0x04, 0x04, 0x00, self.input)
        #print status
    
    def readOutput(self):
        (resp, pay) = self.hw.sendAPDU(0x80, 0xC0, 0x00, 0x00, rxdatalen=16)
        #print resp
        return pay    
               
               
class ProtocolDPAv42(ProtocolTemplate):

    def setupParameters(self):
        """No parameters"""
        #ssParams = []        
        #self.params = Parameter.create(name='Smartcard Reader', type='group', children=ssParams)
        #ExtendedParameter.setupExtended(self.params, self)
        self.params = None
        
    def loadEncryptionKey(self, key):
        if len(key) != 16:
            raise ValueError("Encryption key != 16 bytes??")
        self.key = key
        
    def loadInput(self, inputtext):
        if len(inputtext) != 16:
            raise ValueError("Plaintext != 16 bytes??")
        self.input = inputtext
        
    def go(self):      
        if not isinstance(self.hw, ReaderChipWhispererSER):
            raise IOError("ERROR: DPAContestv4 only works with ChipWhisperer-SER Reader")
            
        data = []
        data.extend(self.key)
        data.extend(self.input)
            
        self.hw.ser.flush()
        self.hw.ser.write([0x80, 0xC0, 0x00, 0x00, 32])
        self.hw.waitEcho([0x80, 0xC0, 0x00, 0x00, 32])
        self.hw.ser.write(data)
        self.hw.waitEcho(data)
        
        #Ack
        ack = self.hw.ser.read(1)
        #print "%02x"%ord(ack[0])
        
        #Random Block
        rblock = self.hw.ser.read(16)
        rblock = [ord(t) for t in rblock]
       
        #Ack
        ack = self.hw.ser.read(1)
        
        #Key + Message sent back
        self.hw.waitEcho(data)
        
        #Ack - shuffle done
        ack = self.hw.ser.read(1)
        
        #Receive shuffle blocks back
        suffle0 = self.hw.ser.read(16)
        suffle0 = [ord(t) for t in suffle0]
        
        suffle1 = self.hw.ser.read(16)
        suffle1 = [ord(t) for t in suffle1]
        
        #Ack - encryption starting now
        ack = self.hw.ser.read(1)
        
        #Ack - encryption done now
        ack = self.hw.ser.read(1)
        
        result = self.hw.ser.read(16)
        result = [ord(t) for t in result]
        
        self.textout = result
    
    def readOutput(self):
        return self.textout   

class ProtocolJCardTest(ProtocolTemplate):

    def setupParameters(self):
        """No parameters"""
        self.params = None

    def loadEncryptionKey(self, key):
        pass

    def loadInput(self, inputtext):
        pass

    def go(self):

        # self.hw.scserv.connection.disconnect()
        # self.hw.con()

        status = self.hw.sendAPDU(0x00, 0xA4, 0x04, 0x00, [0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0x01, 0x01])
        if status != 0x9000:
            raise IOError("Invalid Status: %x" % status)

        (resp, pay) = self.hw.sendAPDU(0x80, 0x10, 0x01, 0x02, [0xAE], rxdatalen=6)
        if  resp != 0x9000:
            raise IOError("Invalid Status: %x" % status)

        counter1 = (pay[5] << 8) | pay[6]
        counter2 = (pay[7] << 8) | pay[8]
        counter3 = (pay[9] << 8) | pay[10]

        self.resp = (counter1, counter2, counter3)



        print self.resp

    def readOutput(self):
        return self.resp

class SmartCard(TargetTemplate):
    paramListUpdated = Signal(list) 
     
    def setupParameters(self):
        self.oa=None
        self.driver = None
        
        supported_readers = dicttype()
        supported_readers["Select Reader"] = None
        supported_readers["ChipWhisperer-SER"] = ReaderChipWhispererSER()
        supported_readers["ChipWhisperer-USI"] = ReaderChipWhispererUSI()
        supported_readers["ChipWhisperer-SCARD"] = ReaderChipWhispererSCard()
        try:
            supported_readers["PC/SC Reader"] = ReaderPCSC()
        except ImportError:
            pass
        
        ssParams = [{'name':'Reader Hardware', 'type':'list', 'values':supported_readers, 'value':None, 'set':self.setConnection},
                    #"BasicCard v7.5 (INCOMPLETE"):None, 
                    #"Custom (INCOMPLETE)":None, "DPAContestv4 (INCOMPLETE)":None
                    {'name':'SmartCard Protocol', 'type':'list', 'values':{"SASEBO-W SmartCard OS":ProtocolSASEBOWCardOS(),
                                                                           "ChipWhisperer-Dumb":None,
                                                                           "JCard Test":ProtocolJCardTest(),
                                                                           "DPA Contest 4.2":ProtocolDPAv42(),
                                                                           }, 'value':None, 'set':self.setProtocol}
                    ]        
        self.params = Parameter.create(name='Target Connection', type='group', children=ssParams)
        ExtendedParameter.setupExtended(self.params, self)

    def __del__(self):
        self.close()

    def setOpenADC(self, oadc):
        try:
            self.oa=oadc
            self.driver.setOpenADC(oadc)
        except:
            pass

    def keyLen(self):
        """ Return key length in BYTES """
        return 16

    def setConnection(self, con):
        self.driver = con        
        self.paramListUpdated.emit(self.paramList)
        
    def setProtocol(self, con):
        self.protocol = con
        self.paramListUpdated.emit(self.paramList)
        self.protocol.setReaderHardware(self.driver)
        
    def paramList(self):
        p = [self.params]
        if self.driver is not None:
            for a in self.driver.paramList(): p.append(a)
        return p
    
    def con(self):       
        self.driver.con(self.oa)
        self.driver.flush()
        self.protocol.setReaderHardware(self.driver)

    def dis(self):
        self.close()
    
    def close(self):
        if self.driver != None:
            self.driver.close()
            self.driver = None
        return
        
    def init(self):
        self.protocol.init()

    def reinit(self):
        self.protocol.reinit()
      
    def loadEncryptionKey(self, key):
        self.protocol.loadEncryptionKey(key)
        self.key = key
      
    def loadInput(self, inputtext):
        self.protocol.loadInput(inputtext)
        self.input = inputtext

    def isDone(self):
        return self.protocol.isDone()

    def readOutput(self):        
        return self.protocol.readOutput()

    def go(self):
        self.protocol.go()

    def setModeEncrypt(self):
        pass
    
    def checkEncryptionKey(self, key):
        return key
