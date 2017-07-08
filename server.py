#!/usr/bin/env python3

import socket, threading, json, traceback

PORT = 5566

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(('', PORT))
s.listen()
clients = []
userIds = {}
lock = threading.Lock()

def log(msg):
	try:
		print(msg)
	except:
		pass

log('Presence server running on port '+str(PORT))
class server(threading.Thread):
	userId = None
	roomId = None
	subscribed = []
	def __init__(self, connectioninfo):
		socket,address = connectioninfo
		threading.Thread.__init__(self)
		self.socket = socket
		self.address = address
		self.username = None
		self.message = b''
		self.userId = None
	def send(self, socket, msg):
		data = json.dumps(msg).encode('utf-8')+b'\r\n'
		socket.send(data)
	def process(self, msg):
		user_methods = {
			'move': 'user_moved',
			'chat': 'user_chat',
			'portal': 'user_portal',
		}
		method = msg.get('method',None)
		data = msg.get('data',None)
		if method and self.userId is None:
			if method == 'logon':
				userId = data.get('userId',None)
				roomId = data.get('roomId',None)
				if roomId is None:
					self.send(self.socket, {'method':'error', 'data':{'message':'Missing roomId in data packet'}})
				if userId and userId not in userIds and len(userId) > 0:
					if self.userId:
						del userIds[self.userId]
					self.userId = userId
					userIds[userId] = {'socket':self, 'roomId':roomId, 'subscribed':[roomId,]}
					self.send(self.socket, {'method':'okay'})
					log(self.userId+' logged in. (%s:%s)' % self.address)
				else:
					self.send(self.socket, {'method':'error','data':{'message':'User name is already in use'}})
			else:
				self.send(self.socket, {'method':'error','data':{'message':'You must call "logon" before sending any other commands.'}})
		elif method and self.userId:
			if method == 'move':
				if data:
					new_method = user_methods[method]
					new_data = data.copy()
					self.relay({'method':new_method, 'data':{'userId':self.userId, 'roomId':self.roomId, 'position':new_data}}, self.roomId)
				else:
					return False
			elif method == 'enter_room':
				roomId = data.get('roomId',None)
				if roomId:
					self.send(self.socket, {'method':'okay'})
					self.relay({'method':'user_leave', 'data':{'userId':self.userId,'roomId':roomId}}, self.roomId)
					self.relay({'method':'user_enter', 'data':{'userId':self.userId,'roomId':roomId}}, roomId)
					self.roomId = roomId
				else:
					return False
			elif method == 'subscribe':
				roomId = data.get('roomId',None)
				if roomId not in self.subscribed:
					self.subscribed.append(roomId)
					userIds[self.userId]['subscribed'] = self.subscribed
				self.send(self.socket, {'method':'okay'})
			elif method == 'unsubscribe':
				roomId = data.get('roomId',None)
				if roomId in self.subscribed:
					self.subscribed.remove(roomId)
					userIds[self.userId]['subscribed'] = self.subscribed
				self.send(self.socket, {'method':'okay'})
			elif method == 'chat':
				if data:
					self.relay({'method':'user_chat','data':{'userId':self.userId, 'message':data}},self.roomId)
				else:
					return False
			elif method == 'portal':
				url = data.get('url',None)
				pos = data.get('pos',None)
				fwd = data.get('fwd',None)
				if url and pos and fwd:
					self.relay( {'method':'user_portal', 'data':{'roomId':self.roomId, 'userId':self.userId, 'url':url, 'pos':pos, 'fwd':fwd}}, self.roomId)
				else:
					return False
				#"data":{"roomId":"e562b2e1339fc08d635d28481121857c","userId":"ProudMinna333","url":"http://www.vrsites.com","pos":"-7.16883 -0.267702 -6.57243","fwd":"0.967686 0 -0.234104"}}
			else:
				return False
		return True

	def relay(self, msg, roomId=None):
		if roomId is None:
			for uid in userIds:
				if uid != self.userId:
					try:
						self.send(userIds[uid]['socket'].socket, msg)
					except:
						pass
		else:
			for uid in userIds:
				if uid != self.userId:
					if userIds[uid].get('roomId',None) == roomId or roomId in userIds[uid].get('subscribed',[]):
						try:
							self.send(userIds[uid]['socket'].socket, msg)
						except:
							pass

	def run(self):
		lock.acquire()
		clients.append(self)
		lock.release()
		log('%s:%s connected.' % self.address)
		while True:
			try:
				data = self.socket.recv(10240)
			except (ConnectionAbortedError, ConnectionResetError):
				break
			if not data:
				break
			data = data.splitlines(keepends=True)
			try:
				data[0] = self.message+data[0]
			except:
				pass
			for line in data:
				if line[-1:] != b'\n':
					self.message += line
					pass
				else:
					self.message = b''
					try:
						if not self.process(json.loads(line.decode('utf-8'))):
							self.send(self.socket, {'method':'error','data':{'message':'Unable to parse last message'}})
							log(line)
					except Exception:
						log(line)
						log(traceback.format_exc())
		self.socket.close()
		if self.userId:
			log(self.userId+' logged out. (%s:%s)' % self.address)
		else:
			log('%s:%s disconnected.' % self.address)
		lock.acquire()
		clients.remove(self)
		if self.userId:
			del userIds[self.userId]
		lock.release()

while True:
	server(s.accept()).start()
