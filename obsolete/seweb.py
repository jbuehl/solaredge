#!/usr/bin/python

import cherrypy
import json
import MySQLdb

# configuration
httpPort = 7380
dataBase = "solar"
dbHostName = "localhost"
userName = ""
password = ""

class WebRoot(object):
    def __init__(self, db):
        self.db = db
        
    @cherrypy.expose
    def stats(self):
        sql = "select * from stats;"
        cur = self.db.cursor()
        if cur.execute(sql) > 0:
            result = json.dumps(dict((cur.description[i][0], value) for i, value in enumerate(cur.fetchall()[0])))
        else:
            result = "{}"
        db.commit()
        cur.close()
        return result
        
    @cherrypy.expose
    def optimizers(self, id=None):
        if id:
            return self.getObject("optstate", id)
        else:
            return self.getList("optattrs")

    @cherrypy.expose
    def inverters(self, id=None):
        if id:
            return self.getObject("invstate", id)
        else:
            return self.getList("invattrs")

    # get the current state of the specified device
    def getObject(self, table, id):
        sql = "select * from "+table+" where id='"+id+"';"
        cur = self.db.cursor()
        if cur.execute(sql) > 0:
            # return the dictionary of key value pairs, skip the first 2 which are date and time
            result = json.dumps(dict((cur.description[i+2][0], value) for i, value in enumerate(cur.fetchall()[0][2:])))
        else:
            result = json.dumps({"ID": id, "Eday": 0.0, "Temp": 0})
        db.commit()
        cur.close()
        return result

    # get the list of devices of the spacified type
    def getList(self, table):
        sql = "select id from "+table+";"
        cur = self.db.cursor()
        if cur.execute(sql) > 0:
            result = json.dumps([row[0] for row in cur.fetchall()])
        else:
            result = "[]"
        cur.close()
        return result
            
if __name__ == "__main__":

    # data base
    db = MySQLdb.connect(host=dbHostName, user=userName, passwd=password, db=dataBase)

    # web interface
    globalConfig = {'server.socket_port': httpPort,
                    'server.socket_host': "0.0.0.0",
                    }
    cherrypy.config.update(globalConfig)
    root = WebRoot(db)
    cherrypy.tree.mount(root, "/", {})
    access_log = cherrypy.log.access_log
    for handler in tuple(access_log.handlers):
        access_log.removeHandler(handler)
    cherrypy.engine.start()


