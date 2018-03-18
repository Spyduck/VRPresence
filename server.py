#!/usr/bin/env python3

import socket, threading, json, traceback, configparser, os, ssl, time, select, asyncio, websockets, importlib

abspath = os.path.abspath(__file__)
dname = os.path.dirname(abspath)
os.chdir(dname)

DOMAIN = 'localhost'
PORT = 5566
PORT_SSL = 5567
USE_SSL = False
CERT = ''
KEY = ''
ADDONS_LIST = ''
if os.path.exists('server.cfg'):
	config = configparser.RawConfigParser()
	config.read('server.cfg')
	DOMAIN = config.get('DEFAULT','domain',fallback='localhost')
	PORT = config.getint('DEFAULT','port',fallback=5566)
	PORT_SSL = config.getint('DEFAULT','port_ssl',fallback=5567)
	USE_SSL = config.getboolean('DEFAULT','use_ssl',fallback=False)
	CERT = config.get('DEFAULT','cert',fallback='')
	KEY = config.get('DEFAULT','key',fallback='')
	ADDONS_LIST = config.get('DEFAULT','addons',fallback='')

addons = []
for addon_name in ADDONS_LIST.split(','):
	if len(addon_name) > 0 and os.path.exists(addon_name+'.py'):
		module = importlib.import_module(addon_name)
		module_class = module.addon()
		addons.append(module_class)


userIds = {}
queues = []
lock = threading.Lock()
client_list = []
disconnect_all = False

def log(msg, silent=False):
	try:
		if silent == False:
			print(msg)
		with open('vrpresence.log','a') as f:
			f.write(str(msg, 'utf-8')+'\n')
	except:
		pass

# call function in each addon
# usage example:
#	pass_to_addons('user_chat', userId='name', message='hello')
def pass_to_addons(function, **kwargs):
	global addons
	if function is not None and kwargs is not None:
		for addon in addons:
			if function in dir(addon):
				func = getattr(addon, function)
				func(**kwargs)

class AsyncServer(threading.Thread):

	use_ws = False
	userId = None
	roomId = None
	subscribed = []
	message = b''
	ws_queue = None
	serv = None
	running = True
	
	def __init__(self, connectioninfo=None):
		if connectioninfo:
			socket, address = connectioninfo
			self.socket = socket
			self.address = address
			self.use_ws = False
		else:
			self.use_ws = True
			#self.ws_queue = queue.Queue()
		threading.Thread.__init__(self, daemon=True)
		#self.daemon = True
	async def send(self, socket, msg, use_ws=None):
		if not isinstance(msg, (bytes, bytearray)):
			msg = json.dumps(msg,separators=(',', ':')).encode('utf-8')
		if not use_ws and self.socket == socket:
			use_ws = self.use_ws
		if use_ws:
			try:
				msg = str(msg, 'utf-8')+'\r\n'
			except:
				msg = msg+'\r\n'
			try:
				await socket.send(msg)
			except Exception as e:
				log(e)
				self.running = False
		else:
			try:
				msg = bytes(msg,'utf-8')+b'\r\n'
			except:
				msg = msg+b'\r\n'
			try:
				socket.send(msg)
			except OSError:
				await self.disconnect()

	async def recv(self, size=1048576):
		if self.use_ws:
			if self.socket:
				try:
					return (await self.socket.recv()).encode('utf-8')
				except websockets.exceptions.ConnectionClosed as e:
					log(e)
					await self.disconnect()
		else:
			if self.socket:
				try:
					ready = select.select([self.socket], [], [], 0)[0]
				except OSError as e:
					return None
				if len(ready) > 0:
					try:
						data = self.socket.recv(size)
						if not data:
							return None
						return data
					except Exception as e:
						return None
				else:
					return b''
		return None
	
	async def setup(self, future=None, socket=None, address=None, serv=None):
		self.serv = serv
		if socket:
			self.socket = socket
		if address:
			self.address = address
		self.message = b''
		self.running = True
		lock.acquire()
		if self.ws_queue:
			queues.append({'socket':self.socket,'queue':self.ws_queue})
		client_list.append(self)
		lock.release()
		log('%s:%s connected.' % self.address)
		pass_to_addons('connect', thread=self)
		
		if future:
			future.set_result(True)
		if not serv:
			while self.running:
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
					pass_to_addons('logon', userId=self.userId, thread=self)
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
					pass_to_addons('user_move', data=new_data, thread=self)
					await self.relay({'method':new_method, 'data':{'userId':self.userId, 'roomId':self.roomId, 'position':new_data}}, self.roomId)
				else:
					return False
			elif method == 'enter_room':
				roomId = data.get('roomId',None)
				if roomId:
					okay = True
					pass_to_addons('user_leave', userId=self.userId, roomId=self.roomId, thread=self)
					pass_to_addons('user_enter', userId=self.userId, roomId=roomId, thread=self)
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
					pass_to_addons('user_chat', userId=self.userId, message=data, thread=self)
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
			lock.acquire()
			ids = userIds.copy()
			lock.release()
			for uid in ids:
				if uid != self.userId:
					try:
						await self.send(userIds[uid]['socket'].socket, msg, userIds[uid]['socket'].use_ws)
					except Exception as e:
						log(e)
		else:
			for uid in userIds.copy():
				if uid != self.userId:
					if userIds[uid].get('roomId',None) == roomId or roomId in userIds[uid].get('subscribed',[]):
						try:
							await self.send(userIds[uid]['socket'].socket, msg, userIds[uid]['socket'].use_ws)

						except Exception as e:
							log(e)
	async def run(self):
		global disconnect_all
		if self.running:
			await asyncio.sleep(0)
			try:
				if disconnect_all:
					await self.disconnect()
				data = await self.recv()
				if data is not None and len(data) > 0:
					self.message += data
					if b'\n' not in data:
						return
				elif data is not None and len(data) == 0:
					return
				elif data is None:
					await self.disconnect()
					return
				if not data:
					await asyncio.sleep(0)
					return
				data = data.splitlines(keepends=True)
				try:
					json.loads(data[0].decode('utf-8',errors='replace'))
					loaded = True
				except:
					loaded = False
				if not loaded:
					return
				for line in data:
					if line[-1:] != b'\n':
						self.message += line
					else:
						self.message = b''
						try:
							packet = json.loads(line.decode('utf-8',errors='replace'))
						except:
							log(traceback.format_exc())
							await self.send(self.socket, {'method':'error','data':{'message':'Unable to parse last message'}})
							continue
						try:
							if not await self.process(packet):
								await self.send(self.socket, {'method':'error','data':{'message':'Unable to parse last message'}})
						except Exception:
							log(line)
							log(traceback.format_exc())
			except KeyboardInterrupt:
				disconnect_all = True
			await asyncio.sleep(0)
		else:
			await self.disconnect()
		
	async def disconnect(self):
		global disconnect_all
		global client_list
		global userIds
		global threads
		if not self.socket:
			return
		lock.acquire(timeout=1)
		if self.userId:
			log(self.userId+' logged out. (%s:%s)' % self.address)
			try:
				pass
				#await self.relay({'method':'user_disconnected', 'data':{'userId':self.userId}}, self.roomId)
			except Exception as e:
				pass
		else:
			log('%s:%s disconnected.' % self.address)
		self.running = False
		try:
			if self.use_ws:
				await self.socket.close()
			else:
				#self.socket.shutdown(socket.SHUT_RD)
				self.socket.close()
		except Exception as e:
			print(e)
		if self.serv and self.serv in threads:
			threads.remove(self.serv)
		if self.userId and self.userId in userIds:
			del userIds[self.userId]
		if self in client_list:
			client_list.remove(self)
		self.socket = None
		lock.release()
		print(len(threads))

if USE_SSL:
	context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
	context.load_cert_chain(certfile=CERT, keyfile=KEY)

async def ssl_connection(websocket, path):
	await AsyncServer().setup(socket=websocket, address=websocket.remote_address)
	
@asyncio.coroutine
async def accept_connection_coro(future, loop):
	global disconnect_all
	global threads
	asyncio.set_event_loop(loop)
	if not disconnect_all:
		sock = None
		ready = select.select([s], [], [], 0.001)[0]
		if len(ready) > 0:
			try:
				sock = s.accept()
			except socket.timeout:
				future.set_result(True)
				return
		if sock:
			serv = AsyncServer(sock)
			lock.acquire()
			threads.append(serv)
			lock.release()
			await serv.setup(serv=serv)
	future.set_result(True)
	
@asyncio.coroutine
async def loop_connections(loop):
	global disconnect_all
	global threads
	asyncio.set_event_loop(loop)
	i = 0
	for this_thread in threads:
		await this_thread.run()
		await asyncio.sleep(0)
		i += 1
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
bound = False
while bound == False:
	try:
		s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		s.bind((DOMAIN, PORT))
		bound = True
	except OSError as e:
		time.sleep(5)
		log(e)
	except KeyboardInterrupt:
		disconnect_all = True
s.listen()

threads = []
if USE_SSL:
	log('Presence server running on ports '+str(PORT)+' and '+str(PORT_SSL))
else:
	log('Presence server running on port '+str(PORT))
loop = asyncio.new_event_loop()
if USE_SSL:
	start_server = websockets.serve(ssl_connection, DOMAIN, PORT_SSL, ssl=context, subprotocols=['binary'])

loop = asyncio.get_event_loop()
try:
	while not disconnect_all:
		future = asyncio.Future()
		asyncio.ensure_future(accept_connection_coro(future,loop))
		loop.run_until_complete(future)
		if USE_SSL:
			loop.run_until_complete(start_server)
		loop.run_until_complete(loop_connections(loop))
		asyncio.sleep(0)
except KeyboardInterrupt:
	disconnect_all = True
finally:
	loop.close()
s.shutdown(socket.SHUT_RDWR)
s.close()