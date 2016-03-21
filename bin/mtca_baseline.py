#!/usr/bin/env python
import time, argparse, os,sys
from minard.timeseries import INTERVALS, EXPIRE
from redis import Redis
try:
	from snotdaq import MTC, Logger
except ImportError:
	sys.path.append('/usr/local/lib/python2.6/site-packages/')
	from snotdaq import MTC, Logger
#The objective here is to retrieve and store baseline values into a redis db
parser = argparse.ArgumentParser()
parser.add_argument("--mtc-server",
help="Set the IP of the MTC server whence the baselines can be retrieved. Default = sbc.snolab.ca",
type=str,default='sbc.sp.snolab.ca')
parser.add_argument("--enable-logging",help="Enables sending errors to log server",
action="store_true")
parser.add_argument("--log-server",help="Set the IP of the log server. Default = daq1.sbc.snolab.ca",
type=str,default="daq1.sp.snolab.ca")
parser.add_argument("--log-port",help="Set the port the log server is at. Default = 4001",
type=int,default=4001)
parser.add_argument("--loop-forever",help="Loops infinitely with 0.5 second period",
action="store_true")
parser.add_argument("--daemonize",help="Runs in background",
action="store_true")
args = parser.parse_args()
if args.enable_logging:
    logger = Logger("BaselineMonitor",args.log_server,args.log_port)
else:
    logger = False;
def OptLog(priority,s):
    if logger:
        logger.log(priority,s)
class mtca_baselines:
    def __init__(self):

        self.DBToMTC = {"100H":"N100HI","100M":"N100MED","100L":"N100LO",
        "20":"N20","20LB":"N20LB","ESUMH":"ESUMHI","ESUML":"ESUMLO",
        "OWLEH":"OWLEHI","OWLEL":"OWLELO","OWLN":"OWLN"}
        self.baselines = {"100H":None,"100M":None,"100L":None,"20":None,
        "20LB":None,"ESUMH":None,"ESUML":None,"OWLEL":None,"OWLEH":None,
        "OWLN":None};
        self.mtc = MTC(parser.mtc_server) #Connect to MTC server
        self.ConversionFactor = -0.5 #TODO empircally determine this value
    def empty(self):
        for key in self.baselines:
            if self.baselines[key] == None:
                return True
        return False
    def getBaseline(self,name):
        self.mtc.send('threshmon '+self.DBToMTC[name])
        reply = self.mtc.recv()
        try:
            val = int(reply)
        except ValueError:
            OptLog(2,"Could not get baselines")
            return
        return self.convertCorrectionToDrift(val)
        #I think this should be float(reply) actually but idk
        #Tony may or may not have updated this command to do doubles
    def flush(self):
        for key in self.baselines:
            self.baselines[key] = None
    def convertCorrectionToDrift(self,correction):
        """The MTCA reads out the amount of baseline correction applied.
            This function uses a calibrated value to convert from correction
            applied to baseline value.
            The conversion is a simple linear scaling"""
        return self.ConversionFactor*correction
    def items(self):
        if self.empty():
            for key in self.baselines:
                yield (key,self.getBaseline(key))

def PutBaselinesInDatabase():
    redis = Redis()
    p = redis.pipeline()
    now = int(time.time())
    try:
        Baselines = mtca_baselines()
    except:
        OptLog(2,"Could not connect to MTC")
        return
    for interval in INTERVALS:
        p.incrby('ts:%i:%i:baseline-count' % (interval,now//interval),1)
        p.expire('ts:%i:%i:baseline-count' % (interval,now//interval),interval*EXPIRE);
        for name,baseline in Baselines.items():
            key = 'ts:%i:%i:%s' % (interval,now//interval,name+"-Baseline")
            p.incrbyfloat(key,baseline)
            p.expire(key,interval*EXPIRE)
        p.execute()
        Baselines.flush()

if __name__ == '__main__':
    if args.daemonize:
        try:
            pid = os.fork()
            if pid>0:
                #kill the parent
                sys.exit(0)
        except OSError,e:
            sys.stderr.write("Failed to create fork: %d (%s)\n" %(e.errno,e.strerror))
            sys.exit(1)
        os.chdir("/")
        os.setsid()
        os.umask(0)
        devNull = open(os.devnull,'w')
        sys.stdout = devNull
        sys.stderr = devNull
    PutBaselinesInDatabase()
    while(args.loop_forever):
        time.sleep(0.5)
        PutBaselinesInDatabase()