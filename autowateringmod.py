import logging
from datetime import datetime, time ,timedelta
import hardwaremod
import os
import subprocess
import emailmod
import autowateringdbmod
import sensordbmod
import actuatordbmod

logger = logging.getLogger("hydrosys4."+__name__)

# status array, required to check the ongoing actions within a watering cycle
elementlist= autowateringdbmod.getelementlist()
AUTO_data={} # dictionary of dictionary
for element in elementlist:
	AUTO_data[element]={"cyclestartdate":datetime.utcnow(),"lastwateringtime":datetime.utcnow(),"cyclestatus":"done", "checkcounter":0, "alertcounter":0, "watercounter":0}
# cyclestartdate, datetime of the latest cycle start
# cyclestatus, describe the status of the cycle: lowthreshold, rampup, done
#     "lowthreshold" means that the cycle is just started with lowthreshold activation, if the lowthreshold persists for several checks them alarm should be issued  
#     "rampup", this is in full auto mode, the status in between the lowthreshold and high, not reach yet high. if this status persist then alarm should be issued
#     "done", ready for next start with lowthreshold

# sample of database filed
# {"element": "", "threshold": ["2.0", "4.0"],"workmode": "None","sensor": "","wtstepsec": "100","maxstepnumber": "3","allowedperiod": ["21:00","05:00"],"maxdaysbetweencycles": "10", "pausebetweenwtstepsmin":"45", "mailalerttype":"warningonly" , "sensorminacceptedvalue":"0.5"}


def cyclereset(element):
	global AUTO_data
	AUTO_data[element]={"cyclestartdate":datetime.utcnow(),"lastwateringtime":datetime.utcnow(),"cyclestatus":"done", "checkcounter":0, "alertcounter":0, "watercounter":0}


def autowateringcheck():

	logger.info('Starting Autowatering Evaluation ')
	# iterate among the water actuators
	elementlist= autowateringdbmod.getelementlist()	
	for element in elementlist:
		print "auto watering check -----------------------------------------> ", element
		logger.info('auto watering check --------------------------> %s', element)
		print AUTO_data[element]
		# check the watering mode
		modelist=["None", "Full Auto" , "Emergency Activation" , "Alert Only"]
		workmode=checkworkmode(element)
		sensor=autowateringdbmod.searchdata("element",element,"sensor")
		maxthreshold=hardwaremod.tonumber(autowateringdbmod.searchdata("element",element,"threshold")[1],0)
		minthreshold=hardwaremod.tonumber(autowateringdbmod.searchdata("element",element,"threshold")[0],maxthreshold)
		# exit condition in case of data inconsistency
		if minthreshold>=maxthreshold:
			print "Data inconsistency , element: " , element
			logger.error("Data inconsistency , element: %s " , element)
			return "data inconsistency"
		
		now = datetime.now()
		nowtime = now.time()
		starttimeh=hardwaremod.toint(autowateringdbmod.searchdata("element",element,"allowedperiod")[0].split(":")[0],0)
		starttimem=hardwaremod.toint(autowateringdbmod.searchdata("element",element,"allowedperiod")[0].split(":")[1],0)
		endtimeh=hardwaremod.toint(autowateringdbmod.searchdata("element",element,"allowedperiod")[1].split(":")[0],1)
		endtimem=hardwaremod.toint(autowateringdbmod.searchdata("element",element,"allowedperiod")[1].split(":")[1],0)
		starttime=time(starttimeh,starttimem)
		endtime=time(endtimeh,endtimem)		
		
		duration=1000*hardwaremod.toint(autowateringdbmod.searchdata("element",element,"wtstepsec"),0)
		maxstepnumber=hardwaremod.toint(autowateringdbmod.searchdata("element",element,"maxstepnumber"),0)
		maxdays=hardwaremod.toint(autowateringdbmod.searchdata("element",element,"maxdaysbetweencycles"),0)
		waitingtime=hardwaremod.toint(autowateringdbmod.searchdata("element",element,"pausebetweenwtstepsmin"),0)
		mailtype=autowateringdbmod.searchdata("element",element,"mailalerttype")
		minaccepted=hardwaremod.tonumber(autowateringdbmod.searchdata("element",element,"sensorminacceptedvalue"),0.1)
		
		# ------------------------ Workmode split
		if workmode=="Full Auto":
			# check if inside the allowed time period
			print "full Auto Mode"
			logger.info('full auto mode --> %s', element)
			timeok=isNowInTimePeriod(starttime, endtime, nowtime)
			print "inside allowed time ", timeok , " starttime ", starttime , " endtime ", endtime
			logger.info('full auto mode')
			if timeok:
				logger.info('inside allowed time')
				belowthr,valid=checkminthreshold(sensor,minthreshold,minaccepted)
				if valid:
					if belowthr:
						logger.info('below threshold')
						# wait to seek a more stable reading of hygrometer
						# check if time between watering events is larger that the waiting time (minutes)
						print ' Previous watering: ' , AUTO_data[element]["lastwateringtime"] , ' Now: ', datetime.utcnow()
						timedifference=timediffinminutes(AUTO_data[element]["lastwateringtime"],datetime.utcnow())
						print 'Time interval between watering steps', timedifference ,'. threshold', waitingtime
						logger.info('Time interval between watering steps %d threshold %d', timedifference,waitingtime)		
						if timedifference>waitingtime:
							print " Sufficinet waiting time"
							logger.info('Sufficient waiting time')	
							# activate watering in case the maxstepnumber is not exceeded					
							if maxstepnumber>AUTO_data[element]["watercounter"]:
								#activate pump		
								hardwaremod.makepulse(element,duration)
								# salva su database
								logger.info('Pump ON %s, optional time for msec = %s', element , duration)
								print 'Pump ON, optional time for msec =', duration
								actuatordbmod.insertdataintable(element,duration)
								# invia mail, considered as info, not as alert
								if mailtype!="warningonly":
									textmessage="INFO: " + sensor + " value below the minimum threshold " + str(minthreshold) + ", activating the watering :" + element
									emailmod.sendallmail("alert", textmessage)
								AUTO_data[element]["watercounter"]=AUTO_data[element]["watercounter"]+1
								AUTO_data[element]["lastwateringtime"]=datetime.utcnow()
							else:
								# invia mail if couner alert is lower than 1
								logger.info('Number of watering time per cycle has been exceeeded')
								if AUTO_data[element]["alertcounter"]<1:
									textmessage="WARNING "+ sensor + " value below the minimum threshold " + str(minthreshold) + " still after activating the watering :" + element + " for " + str(maxstepnumber) + " times"
									print textmessage
									#send alert mail notification
									emailmod.sendallmail("alert", textmessage)							
									logger.error(textmessage)
									AUTO_data[element]["alertcounter"]=AUTO_data[element]["alertcounter"]+1
						# update the status
						AUTO_data[element]["cyclestatus"]="lowthreshold"
						AUTO_data[element]["checkcounter"]=AUTO_data[element]["checkcounter"]+1

						
					# rumpup case above threshold but below maxthreshold
					elif sensorreading(sensor)<maxthreshold: # intermediate state where the sensor is above the minthreshold but lower than the max threshold
						# check the status of the automatic cycle
						if AUTO_data[element]["cyclestatus"]!="done":
							status="rampup"							
							# wait to seek a more stable reading of hygrometer
							# check if time between watering events is larger that the waiting time (minutes)			
							if timediffinminutes(AUTO_data[element]["lastwateringtime"],datetime.utcnow())>waitingtime:
								if maxstepnumber>AUTO_data[element]["watercounter"]:
									#activate pump		
									hardwaremod.makepulse(element,duration)
									# salva su database
									logger.info('%s Pump ON, optional time for msec = %s', element, duration)
									print 'Pump ON, optional time for msec =', duration
									actuatordbmod.insertdataintable(element,duration)
									# invia mail, considered as info, not as alert
									if mailtype!="warningonly":
										textmessage="INFO: " + sensor + " value below the Maximum threshold " + str(maxthreshold) + ", activating the watering :" + element
										emailmod.sendallmail("alert", textmessage)
									AUTO_data[element]["watercounter"]=AUTO_data[element]["watercounter"]+1
									AUTO_data[element]["lastwateringtime"]=datetime.utcnow()
								else:
									# give up to reache the maximum threshold, proceed as done, send alert
									logger.info('Number of watering time per cycle has been exceeeded')
									status="done"
									AUTO_data[element]["watercounter"]=0
									AUTO_data[element]["checkcounter"]=-1
									# invia mail if couner alert is lower than 1
									if AUTO_data[element]["alertcounter"]<2:
										textmessage="INFO "+ sensor + " value below the Maximum threshold " + str(maxthreshold) + " still after activating the watering :" + element + " for " + str(maxstepnumber) + " times"
										print textmessage
										#send alert mail notification
										emailmod.sendallmail("alert", textmessage)							
										logger.error(textmessage)
										AUTO_data[element]["alertcounter"]=AUTO_data[element]["alertcounter"]+1
							# update the status
							AUTO_data[element]["cyclestatus"]=status
							AUTO_data[element]["checkcounter"]=AUTO_data[element]["checkcounter"]+1
					
					else:
						# update the status
						AUTO_data[element]["cyclestatus"]="done"
						AUTO_data[element]["checkcounter"]=0
						AUTO_data[element]["watercounter"]=0
						AUTO_data[element]["alertcounter"]=0
														
			
			
		elif workmode=="Emergency Activation":
			# check if inside the allow time period
			timeok=isNowInTimePeriod(starttime, endtime, nowtime)
			print "inside allowed time ", timeok , " starttime ", starttime , " endtime ", endtime
			if timeok:			
				belowthr,valid=checkminthreshold(sensor,minthreshold,minaccepted)
				if valid:
					if belowthr:
						# wait to seek a more stable reading of hygrometer
						# check if time between watering events is larger that the waiting time (minutes)			
						if timediffinminutes(AUTO_data[element]["lastwateringtime"],datetime.utcnow())>waitingtime:
							# activate watering in case the maxstepnumber is not exceeded					
							if maxstepnumber>AUTO_data[element]["watercounter"]:			
								#activate pump		
								hardwaremod.makepulse(element,duration)
								# salva su database
								logger.info('Pump ON, optional time for msec = %s', duration)
								print 'Pump ON, optional time for msec =', duration
								actuatordbmod.insertdataintable(element,duration)
								# invia mail, considered as info, not as alert
								if mailtype!="warningonly":
									textmessage="INFO: " + sensor + " value below the minimum threshold " + str(minthreshold) + ", activating the watering :" + element
									emailmod.sendallmail("alert", textmessage)
								AUTO_data[element]["watercounter"]=AUTO_data[element]["watercounter"]+1
								AUTO_data[element]["lastwateringtime"]=datetime.utcnow()
							else:
								logger.info('Number of watering time per cycle has been exceeeded')
								# invia mail if couner alert is lower than 1
								if AUTO_data[element]["alertcounter"]<1:
									textmessage="WARNING "+ sensor + " value below the minimum threshold " + str(minthreshold) + " still after activating the watering :" + element + " for " + str(maxstepnumber) + " times"
									print textmessage
									#send alert mail notification
									emailmod.sendallmail("alert", textmessage)							
									logger.error(textmessage)
									AUTO_data[element]["alertcounter"]=AUTO_data[element]["alertcounter"]+1
						# update the status
						AUTO_data[element]["cyclestatus"]="lowthreshold"
						AUTO_data[element]["checkcounter"]=AUTO_data[element]["checkcounter"]+1
					else:
						# update the status
						AUTO_data[element]["cyclestatus"]="done"
						AUTO_data[element]["checkcounter"]=0
						AUTO_data[element]["watercounter"]=0
						AUTO_data[element]["alertcounter"]=0				
		
		elif workmode=="Alert Only":
			belowthr,valid=checkminthreshold(sensor,minthreshold,minaccepted)
			if valid:
				if belowthr:
					# invia mail if couter alert is lower than 
					if AUTO_data[element]["alertcounter"]<2:
						textmessage="WARNING "+ sensor + " value below the minimum threshold " + str(minthreshold) + " watering system: " + element
						print textmessage
						#send alert mail notification
						emailmod.sendallmail("alert", textmessage)							
						logger.error(textmessage)
						AUTO_data[element]["alertcounter"]=AUTO_data[element]["alertcounter"]+1
					# update the status
					AUTO_data[element]["cyclestatus"]="lowthreshold"
					AUTO_data[element]["checkcounter"]=AUTO_data[element]["checkcounter"]+1
				else:
					# update the status
					AUTO_data[element]["cyclestatus"]="done"
					AUTO_data[element]["checkcounter"]=0
					AUTO_data[element]["watercounter"]=0
					AUTO_data[element]["alertcounter"]=0					
							
			
		else: # None case
			print "No Action required, workmode set to None, element: " , element
			logger.info("No Action required, workmode set to None, element: %s " , element)

		if AUTO_data[element]["cyclestatus"]=="lowthreshold":
			if AUTO_data[element]["checkcounter"]==1:			
				AUTO_data[element]["cyclestartdate"]=datetime.utcnow()

		# implment alert message for the cycle exceeding days, and reset the cycle
		if timediffdays(datetime.utcnow(),AUTO_data[element]["cyclestartdate"]) > maxdays:
			textmessage="WARNING "+ sensor + " watering cycle is taking too many days, watering system: " + element + ". Reset watering cycle"
			print textmessage
			#send alert mail notification
			emailmod.sendallmail("alert", textmessage)							
			logger.error(textmessage)
			logger.error("Cycle started %s, Now is %s ", AUTO_data[element]["cyclestartdate"].strftime("%Y-%m-%d %H:%M:%S"), datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))			
			# reset cycle
			AUTO_data[element]["cyclestatus"]="done"
			AUTO_data[element]["checkcounter"]=0
			AUTO_data[element]["watercounter"]=0
			AUTO_data[element]["alertcounter"]=0
			AUTO_data[element]["cyclestartdate"]=datetime.utcnow()	


def timediffinminutes(data2, data1):
	diff =  data1 - data2
	return abs(diff.days*1440 + diff.seconds/60)


def timediffdays(data2, data1):
	diff =  data1 - data2
	return abs(diff.days)


def isNowInTimePeriod(startTime, endTime, nowTime):
    if startTime < endTime:
        return nowTime >= startTime and nowTime <= endTime
    else: #Over midnight
        return nowTime >= startTime or nowTime <= endTime

	

def checkminthreshold(sensor,minthreshold,minaccepted):
	belowthr=False
	validity=True		
	# check the hygrometer sensor levels 
	sensorreadingaverage=sensorreading(sensor)
	# if the average level after 4 measure (15 min each) is below threshold apply emergency 
	print " Min accepted threshold " , minaccepted
	if (sensorreadingaverage>minaccepted):
		if (sensorreadingaverage>minthreshold):		
			logger.info('Soil moisture check, Sensor reading=%s > Minimum threshold=%s ', str(sensorreadingaverage), str(minthreshold))			
			print 'Soil moisture check, Sensor reading=%s > Minimum threshold=%s '
		else:
			logger.warning('Soil moisture check, Sensor reading=%s < Minimum threshold=%s ', str(sensorreadingaverage), str(minthreshold))			
			logger.info('Start watering procedure ')			
			print 'Soil moisture check, activating watering procedure '
			belowthr=True
	else:	
		logger.warning('Sensor reading lower than acceptable values %s no action', str(sensorreadingaverage))
		print 'Sensor reading lower than acceptable values ', sensorreadingaverage ,' no action'
		validity=False

	return belowthr, validity



def sensorreading(sensorname):
	MinutesOfAverage=70 #about one hour, 4 samples at 15min samples rate
	if sensorname:
		sensordata=[]		
		sensordbmod.getsensordbdata(sensorname,sensordata)
		starttimecalc=datetime.now()-timedelta(minutes=int(MinutesOfAverage))
		quantity=sensordbmod.EvaluateDataPeriod(sensordata,starttimecalc,datetime.now())["max"]	
	return 	quantity

def lastsensorreading(sensorname):
	if sensorname:
		sensordata=[]		
		sensordbmod.getsensordbdata(sensorname,sensordata)
		data=sensordata[-1]
		try:
			number=float(data[1])
		except:
			number=0
	return 	number	
	
			

def checkworkmode(element):
	return autowateringdbmod.searchdata("element",element,"workmode")






if __name__ == '__main__':
	
	"""
	prova functions
	"""

	

