#!/usr/bin/env python

# This file was created by Ryan Cooper in 2016 for a Raspberry Pi
# This class controls the motors for the robot which are configured as 
# a differential drive
import RPi.GPIO as GPIO
import time
import sys

from multiprocessing import Process
from multiprocessing import Queue
from multiprocessing import Pipe

import util

class MotorController(Process):
	LEFT = 0
	RIGHT = 1

	pwmPin = [38, 37]
	# assuming you're using a L298n and a rpi
	dirPin = [[31,32], [35,33]]

	pwmObj = [None, None]
	# flag for motors pwmObj is started
	pwmStarted = [False, False]
	freq = 60#Hertz
	maxDC = 100
	minDC = 25
	mPowers = [0, 0]
	direction = [0, 0]	# forward or backward
	# set by time.time(), used to stop bot when dced
	lastQueue = 0
	go = True
	# only consumes the queue
	encQueue = None
	controllerQueue = None
	# used to shut the process down
	pipe = None

	def __init__(self, *args, **kwargs):
		super(MotorController, self).__init__()
		for key in kwargs:
			if key == 'encQueue':
				self.encQueue = kwargs[key]
			elif key == 'pipe':
				self.pipe = kwargs[key]
			elif key == 'controllerQueue':
				self.controllerQueue = kwargs[key]
		self.setupPins()
		self.initializePWM()

	def setupPins(self):
		GPIO.setmode(GPIO.BOARD)
		GPIO.setwarnings(False)
		for i in range(0, 2):
			GPIO.setup(self.pwmPin[i], GPIO.OUT)
			for j in range(0, 2):
				GPIO.setup(self.dirPin[j][i], GPIO.OUT)

	def initializePWM(self):
		for i in range(0 ,2):
			self.setDirections()
		for i in range(0, 2):
			self.pwmObj[i] = GPIO.PWM(self.pwmPin[i], self.freq)
			self.pwmStarted[i] = False

	def setDirections(self):
		for i in range(0, 2):
			if self.direction[i]:
				GPIO.output(self.dirPin[i][0], GPIO.HIGH)
				GPIO.output(self.dirPin[i][1], GPIO.LOW)
			else:
				GPIO.output(self.dirPin[i][0], GPIO.LOW)
				GPIO.output(self.dirPin[i][1], GPIO.HIGH)

	# set PWM duty cycle
	def setDC(self):
		for i in range(0 ,2):
			self.setDirections()
		for i in range(0, 2):
			if self.mPowers[i] == 0:
				self.pwmObj[i].stop()
				self.pwmStarted[i] = False
			else:
				if self.pwmStarted[i]:
					self.pwmObj[i].ChangeDutyCycle(self.mPowers[i])
				else:
					self.pwmObj[i].start(self.mPowers[i])
					self.pwmStarted[i] = True

	def exitGracefully(self):
		for i in range(0, 2):
			if self.pwmObj[i]:
				self.pwmObj[i].ChangeDutyCycle(0)
				self.pwmObj[i].stop()
		GPIO.cleanup()
		self.go = False

	def steeringThrottle(self, data):
		steering = data[1]
		throttle = data[2]
		maxSm = 35
		maxSp = 220
		maxMove = 220
		minMove = 0
		sm = transform(abs(steering), 0, 1, 0, maxSm)
		sp = transform(abs(steering), 0, 1, 0, maxSp)
		t = transform(abs(throttle), 0, 1, self.minMove, self.maxMove)
		L = t
		R = t
		end = 1500
		if throttle < 0:
			if steering < 0:
				L += sm
				R -= sp
			else:
				L -= sp
				R += sm
			end = 2000
		else:
			if steering < 0:
				L -= sp
				R += sm
			else:
				L += sm
				R -= sp
			end = 1000
		mL = transform(clampToRange(L, 0, 255), 0, 255, 1500, end)
		mR = transform(clampToRange(R, 0, 255), 0, 255, 1500, end)
		self.changeMotorVals(mL, mR)

	# this function will consume the controllerQueue, which was filled by DDMCServer
	# and will change the motors powers and directions according to what was in the queue
	# it also will monitor that the bot is still receiving commands, and if it isn't, it will stop the bot
	def handleControllerQueue(self):
		# if there hasn't been anything in the queue in half a second
		if time.time()-self.lastQueue > .5 and self.controllerQueue.empty():
			# stop the bot
			self.direction = [0, 0]
			self.mPowers = [0, 0]
			self.lastQueue = time.time()
		else:
			while not self.controllerQueue.empty(): # this is a while so that the most recent thing in the queue is the resultant command that is done
				good = True
				try:
					# nowait because this process was called from the main loop which controls the motors
					# so we don't want this function to block.
					data = self.controllerQueue.get_nowait()
				except Queue.Empty as msg: 
					# realistically this should never happen because we check to see that the queue is not empty
					# but it is shared memory, and who knows?
					good = False
				if good:
					mL = 1500
					mR = 1500
					if data[0] == 1 or data[0] == 3: # recieved motor level commands
						mL = data[1]
						mR = data[2]
						self.changeMotorVals()
					elif data[0] == 2: # recieved joystick information (throttle, steering)
						self.steeringThrottle(data)# this calls changeMotorVals()
				self.lastQueue = time.time()

	# this sets up the values used to drive the motors 
	# it does not drive the motor because this function is tied to the queue
	# and only gets executed when something is in the queue
	# yet we want the motors to be constantly receiving contol information
	# 1000 <= mL,mR <= 2000, 1500 means the wheels wont turn
	def changeMotorVals(self, mL, mR):
		if mL > 1500:
			self.direction[self.LEFT] = 1
			self.mPowers[self.LEFT] = clampToRange(transform(mL, 1500, 2000, 0, 100), 0, self.maxDC)
		else:
			self.direction[self.LEFT] = 0
			self.mPowers[self.LEFT] = clampToRange(transform(mL, 1500, 1000, 0, 100), 0, self.maxDC)
		if self.mPowers[self.LEFT] < self.minDC:
			self.mPowers[self.LEFT] = 0
		if mR > 1500:
			self.direction[self.RIGHT] = 0
			self.mPowers[self.RIGHT] = clampToRange(transform(mR, 1500, 2000, 0, 100), 0, self.maxDC)
		else :
			self.direction[self.RIGHT] = 1
			self.mPowers[self.RIGHT] = clampToRange(transform(mR, 1500, 1000, 0, 100), 0, self.maxDC)
		if self.mPowers[self.RIGHT] < self.minDC:
			self.mPowers[self.RIGHT] = 0

	def handleEncoderQueues(self):
		while not self.encQueue.empty():
			good = True
			try: 
				# nowait because this process was called from the main loop which controls the motors
				# so we don't want this function to block.
				data = self.encQueue.get_nowait()
			except Queue.Empty as msg:
				# realistically this should never happen because we check to see that the queue is not empty
				# but it is shared memory, and who knows?
				good = False
			if good:
				pass

	# check to see if the process should stop
	def checkIfShouldStop(self):
		if self.pipe.poll():
			data = self.pipe.recv()
			if 'stop' in data:
				self.go = False
				self.pipe.close()

	def run(self):
		self.go = True
		try:
			while self.go:
			#	print self.mPowers
			#	print self.direction
				self.handleControllerQueue()
				self.handleEncoderQueues()
				self.setDC()
				#TODO handle queue info which has encoder stuff in it
				self.checkIfShouldStop()
				time.sleep(.01)
			self.exitGracefully()
		except Exception as msg:
			print msg
