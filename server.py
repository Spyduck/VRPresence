#!/usr/bin/env python3

import socket, threading, json, traceback, configparser, os, threading, socket, ssl, queue
import asyncio, websockets

DOMAIN = 'localhost'
PORT = 5566
PORT_SSL = 5567
USE_SSL = False
CERT = ''
KEY = ''

if os.path.exists('server.cfg'):
	config = configparser.RawConfigParser()
	config.read('server.cfg')
	DOMAIN = config.get('DEFAULT','domain',fallback='localhost')
	PORT = config.getint('DEFAULT','port',fallback=5566)
	PORT_SSL = config.getint('DEFAULT','port_ssl',fallback=5567)
	USE_SSL = config.getboolean('DEFAULT','use_ssl',fallback=False)
	CERT = config.get('DEFAULT','cert',fallback='')
	KEY = config.get('DEFAULT','key',fallback='')

userIds = {}
queues = []
lock = threading.Lock()

def log(msg):
	try:
		print(msg)
		with open('log.txt','a') as f:
			f.write(msg+'\n')
	except:
		pass

class Server(threading.Thread):
	use_ws = False
	userId = None
	roomId = None
	subscribed = []
	message = b''
	def __init__(self, connectioninfo):
		socket, address = connectioninfo
		threading.Thread.__init__(self)
		self.socket = socket
		self.address = address

	def send(self, socket, msg, ws_queue=None):
		if not isinstance(msg, (bytes, bytearray)):
			msg = json.dumps(msg,separators=(',', ':')).encode('utf-8') + b'\r\n'
		else:
			msg = msg + b'\r\n'
		if ws_queue:
			msg = msg.decode('utf-8')
			ws_queue.put(msg)
		else:
			socket.send(msg)

	def recv(self, size=10240):
		return self.socket.recv(size)

	def process(self, msg):
		error = None
		okay = False
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
					error = 'Missing roomId in data packet'
				if userId and userId not in userIds and len(userId) > 0:
					self.userId = userId
					lock.acquire()
					userIds[userId] = {'socket':self, 'websocket':self.use_ws, 'roomId':roomId, 'subscribed':[roomId,]}
					lock.release()
					okay = True
					log(self.userId+' logged in. (%s:%s)' % self.address)
				else:
					error = 'User name is already in use'
			else:
				error = 'You must call "logon" before sending any other commands.'
		elif method and self.userId:
			if method == 'move':
				if data:
					new_method = user_methods[method]
					new_data = data.copy()
					new_data['_userId'] = self.userId
					self.relay({'method':new_method, 'data':{'userId':self.userId, 'roomId':self.roomId, 'position':new_data}}, self.roomId)
				else:
					return False
			elif method == 'enter_room':
				roomId = data.get('roomId',None)
				if roomId:
					okay = True
					self.relay({'method':'user_leave', 'data':{'userId':self.userId,'roomId':roomId}}, self.roomId)
					self.relay({'method':'user_enter', 'data':{'userId':self.userId,'roomId':roomId}}, roomId)
					self.roomId = roomId
				else:
					return False
			elif method == 'subscribe':
				roomId = data.get('roomId',None)
				if roomId not in self.subscribed:
					self.subscribed.append(roomId)
					lock.acquire()
					userIds[self.userId]['subscribed'] = self.subscribed
					lock.release()
				okay = True
			elif method == 'unsubscribe':
				roomId = data.get('roomId',None)
				if roomId in self.subscribed:
					self.subscribed.remove(roomId)
					lock.acquire()
					userIds[self.userId]['subscribed'] = self.subscribed
					lock.release()
				okay = True
			elif method == 'chat':
				if data:
					log(self.userId + ' ' + data)
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
			elif method == 'users_online':
				return False # TODO
			else:
				return False
		if error:
			self.send(self.socket, {'method':'error', 'data':{'message':error}})
		elif okay:
			self.send(self.socket, {'method':'okay'})
		return True

	def relay(self, msg, roomId=None):
		if not isinstance(msg, (bytes, bytearray)):
			msg = json.dumps(msg,separators=(',', ':')).encode('utf-8')
		if roomId is None:
			for uid in userIds:
				if uid != self.userId:
					try:
						self.send(userIds[uid]['socket'].socket, msg, ws_queue=userIds[uid].get('queue',None))
					except:
						pass
		else:
			for uid in userIds.copy():
				if uid != self.userId:
					if userIds[uid].get('roomId',None) == roomId or roomId in userIds[uid].get('subscribed',[]):
						try:
							self.send(userIds[uid]['socket'].socket, msg, ws_queue=userIds[uid].get('queue',None))
						except:
							pass

	def run(self):
		log('%s:%s connected.' % self.address)
		running = True
		while running:
			try:
				try:
					data = self.recv(1048576)
				except (ConnectionAbortedError, ConnectionResetError, OSError) as e:
					log(e)
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
							if not self.process(json.loads(line.decode('utf-8',errors='replace'))):
								self.send(self.socket, {'method':'error','data':{'message':'Unable to parse last message'}})
						except Exception:
							log(line)
							log(traceback.format_exc())
			except KeyboardInterrupt:
				running = False
				break
		self.socket.close()
		if self.userId:
			log(self.userId+' logged out. (%s:%s)' % self.address)
			self.relay({'method':'uesr_disconnected', 'data':{'userId':self.userId}}, self.roomId)
		else:
			log('%s:%s disconnected.' % self.address)
		if self.userId:
			lock.acquire()
			del userIds[self.userId]
			lock.release()

class AsyncServer(Server):
	use_ws = True
	ws_queue = queue.Queue()
	def __init__(self):
		pass

	async def send(self, socket, msg, use_ws=True):
		if not isinstance(msg, (bytes, bytearray)):
			msg = json.dumps(msg,separators=(',', ':')).encode('utf-8')
		if use_ws:
			msg = msg.decode('utf-8')+'\r\n'

			try:
				await socket.send(msg)
			except:
				self.running = False
		else:
			try:
				msg = msg.encode('utf-8')+b'\r\n'
			except:
				msg = msg+b'\r\n'
			socket.send(msg)

	async def recv(self):
		data = (await self.socket.recv()).encode('utf-8')
		return data

	async def setup(self, socket, address):
		self.socket = socket
		self.address = address
		self.message = b''
		self.running = True
		lock.acquire()
		queues.append({'socket':self.socket,'queue':self.ws_queue})
		lock.release()
		await self.run()

	async def process(self, msg):
		error = None
		okay = False
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
					error = 'Missing roomId in data packet'
				if userId and userId not in userIds and len(userId) > 0:
					self.userId = userId
					lock.acquire()
					userIds[userId] = {'socket':self, 'websocket':self.use_ws, 'queue':self.ws_queue, 'roomId':roomId, 'subscribed':[roomId,]}
					lock.release()
					okay = True
					log(self.userId+' logged in. (%s:%s)' % self.address)
				else:
					error = 'User name is already in use'
			else:
				error = 'You must call "logon" before sending any other commands.'
		elif method and self.userId:
			if method == 'move':
				if data:
					new_method = user_methods[method]
					new_data = data.copy()
					new_data['_userId'] = self.userId
					await self.relay({'method':new_method, 'data':{'userId':self.userId, 'roomId':self.roomId, 'position':new_data}}, self.roomId)
				else:
					return False
			elif method == 'enter_room':
				roomId = data.get('roomId',None)
				if roomId:
					okay = True
					await self.relay({'method':'user_leave', 'data':{'userId':self.userId,'roomId':roomId}}, self.roomId)
					await self.relay({'method':'user_enter', 'data':{'userId':self.userId,'roomId':roomId}}, roomId)
					self.roomId = roomId
				else:
					return False
			elif method == 'subscribe':
				roomId = data.get('roomId',None)
				if roomId not in self.subscribed:
					self.subscribed.append(roomId)
					lock.acquire()
					userIds[self.userId]['subscribed'] = self.subscribed
					lock.release()
				okay = True
			elif method == 'unsubscribe':
				roomId = data.get('roomId',None)
				if roomId in self.subscribed:
					self.subscribed.remove(roomId)
					lock.acquire()
					userIds[self.userId]['subscribed'] = self.subscribed
					lock.release()
				okay = True
			elif method == 'chat':
				if data:
					log(self.userId + ' ' + data)
					await self.relay({'method':'user_chat','data':{'userId':self.userId, 'message':data}},self.roomId)
				else:
					return False
			elif method == 'portal':
				url = data.get('url',None)
				pos = data.get('pos',None)
				fwd = data.get('fwd',None)
				if url and pos and fwd:
					await self.relay( {'method':'user_portal', 'data':{'roomId':self.roomId, 'userId':self.userId, 'url':url, 'pos':pos, 'fwd':fwd}}, self.roomId)
				else:
					return False
			else:
				return False
		if error:
			await self.send(self.socket, {'method':'error', 'data':{'message':error}})
		elif okay:
			await self.send(self.socket, {'method':'okay'})
		return True

	async def relay(self, msg, roomId=None):
		if isinstance(msg, dict):
			msg = json.dumps(msg,separators=(',', ':')).encode('utf-8')
		if roomId is None:
			for uid in userIds.copy():
				if uid != self.userId:
					try:
						await self.send(userIds[uid]['socket'].socket, msg, userIds[uid]['socket'].use_ws)
					except:
						pass
		else:
			for uid in userIds:
				if uid != self.userId:
					if userIds[uid].get('roomId',None) == roomId or roomId in userIds[uid].get('subscribed',[]):
						try:
							await self.send(userIds[uid]['socket'].socket, msg, userIds[uid]['socket'].use_ws)

						except:
							pass

	async def run(self):
		log('%s:%s connected.' % self.address)
		while self.running:
			try:
				data = await self.recv()
			except (ConnectionAbortedError, ConnectionResetError, OSError, websockets.exceptions.ConnectionClosed) as e:
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
						if not await self.process(json.loads(line.decode('utf-8',errors='replace'))):
							await self.send(self.socket, {'method':'error','data':{'message':'Unable to parse last message'}})
					except Exception:
						log(line)
						log(traceback.format_exc())
		lock.acquire()
		if self.userId:
			del userIds[self.userId]
		for i in range(len(queues)-1):
			if queues[i].get('socket') == self.socket:
				queues.pop(i)
		lock.release()
		self.socket.close()
		if self.userId:
			log(self.userId+' logged out. (%s:%s)' % self.address)
			await self.relay({'method':'uesr_disconnected', 'data':{'userId':self.userId}}, self.roomId)
		else:
			log('%s:%s disconnected.' % self.address)
if USE_SSL:
	context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
	context.load_cert_chain(certfile=CERT, keyfile=KEY)

async def ssl_connection(websocket, path):
	s2 = await AsyncServer().setup(websocket, websocket.remote_address)

def accept_connections():
	while True:
		Server(s.accept()).start()

def accept_ssl_connections():
	start_server = websockets.serve(ssl_connection, DOMAIN, PORT_SSL, ssl=context, subprotocols=['binary'])
	loop = asyncio.get_event_loop()
	try:
		loop.run_until_complete(start_server)
		loop.run_forever()
	finally:
		loop.close()


s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind((DOMAIN, PORT))
s.listen()

@asyncio.coroutine
async def process_queue(future):
	rem_queues = []
	for q in queues:
		socket = q.get('socket',None)
		queued = q.get('queue',None)

		if not queued.empty():
			line = queued.get()
			try:
				await socket.send(line)
			except:
				rem_queues.append(q)
				#log(traceback.format_exc())
	for q in rem_queues:
		queues.remove(q)
	await asyncio.sleep(0.02)
	future.set_result(True)

if USE_SSL:
	log('Presence server running on ports '+str(PORT)+' and '+str(PORT_SSL))
	threading.Thread(target=accept_connections,daemon=True).start()
	start_server = websockets.serve(ssl_connection, DOMAIN, PORT_SSL, ssl=context, subprotocols=['binary'])
	loop = asyncio.get_event_loop()
	try:
		while True:
			future = asyncio.Future()
			asyncio.ensure_future(process_queue(future))
			loop.run_until_complete(future)
			loop.run_until_complete(start_server)
			#asyncio.sleep(0.1)
	finally:
		loop.close()
else:
	log('Presence server running on port '+str(PORT))
	accept_connections()
