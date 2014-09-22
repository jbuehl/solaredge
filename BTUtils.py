import inspect
import json
import time

class BTObject(object):
    def __init__(self, theName, theApp, label=""):
        self.name = theName
        self.app = theApp
        if label == "":
            self.label = self.name
        else:
            self.label = label
        if self.app.debugObject: self.app.log(self.name, "created")

class BTApp(object):
    def __init__(self, configFileName, logFileName, config):
        self.running = True         # True until something terminates the program
        self.configFileName = configFileName
        self.logFileName = logFileName
        self.setConfig(config)
        self.readConfig()

    def setConfig(self, config, override=True):
        for item in config.keys():
            try:
                attr = getattr(self, item)
                if override:
                    setattr(self, item, config[item])
            except AttributeError:
                setattr(self, item, config[item])
     
    def readConfig(self):
        try:
            configFile = open(self.configFileName)
            config = {}
            for line in configFile:
                try:
                    line = line[:line.find("#")].strip()
                    if line != "":
                        param = line.split("=")
                        config[param[0].strip()] = eval(param[1].strip())
                except:
                    print "Bad configuration parameter"
                    print line
            self.setConfig(config)
            configFile.close()
        except:
            pass
    
    def log(self, *args):
        message = "%-16s: "%args[0]
        for arg in args[1:]:
            message += arg.__str__()+" "
        logFile = open(self.logFileName, "a")
        logFile.write(time.strftime("%Y-%m-%d %H:%M:%S")+" - "+message+"\n")
        logFile.close()

