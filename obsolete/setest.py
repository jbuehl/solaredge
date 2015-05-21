import json
import urllib2

url = "http://192.168.1.56/"
invs = json.load(urllib2.urlopen(url+"inverters"))
Pac = 0
Eday = 0
for inv in invs:
    idat = json.load(urllib2.urlopen(url+"inverters?id="+inv))
    Pac += idat["Pac"]
    Eday += idat["Eday"]
print "%s Temp: %dF Power: %dW Today: %dWh" % (idat["timeStamp"], idat["Temp"], Pac, Eday)
    
