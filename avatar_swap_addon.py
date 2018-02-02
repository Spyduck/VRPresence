import hashlib

class addon():
	global_avatar = "<FireBoxRoom><Assets><AssetObject id=^body^ src=^https://assets.spyduck.net/avatar/obj/mallard/mallard.obj.gz^ tex_linear=^false^ /></Assets><Room><Ghost id=^januswebuser^ scale=^1 1 1^ body_id=^body^ anim_id=^idle^ eye_pos=^0 0.85 0^ /></Room></FireBoxRoom>"
	rooms = []
	
	def __init__(self):
		self.log('Avatar Swap Addon initialized')
		self.rooms.append(self.md5('https://vesta.janusvr.com/spyduck/centralia-church'))
		self.rooms.append(self.md5('https://paradox.spyduck.net/rooms/lostsouls/church.php'))
		self.rooms.append(self.md5('https://vesta.janusvr.com/spyduck/celestial-events-dreamscapes-1'))
		
	def user_chat(self, userId=None, message=None, thread=None):
		self.log(userId+': '+message)
	
	def logon(self, userId=None, thread=None):
		pass
	
	def user_move(self, data=None, thread=None):
		if thread.roomId in self.rooms and 'avatar' in data:
			data['avatar'] = self.global_avatar
			thread.data = data
	
	def user_leave(self, userId=None, roomId=None, thread=None):
		pass
	
	def user_enter(self, userId=None, roomId=None, thread=None):
		if roomId in self.rooms:
			self.log(userId + ' has joined the paddling.')
		pass
	
	def log(self, msg, silent=False):
		try:
			if silent == False:
				print(msg)
			with open('vrpresence.log','a') as f:
				f.write(str(msg, 'utf-8')+'\n')
		except:
			pass
			
	def md5(self, data):
		m = hashlib.md5()
		m.update(bytes(data, 'utf-8'))
		return m.hexdigest()
		