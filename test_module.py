class addon():
	def __init__(self):
		print('test_module Addon initialized')
	
	def connect(self, thread=None):
		pass
	
	def user_chat(self, userId=None, message=None, thread=None):
		self.log(userId+': '+message)
	
	def logon(self, userId=None, thread=None):
		pass
	
	def user_move(self, data=None, thread=None):
		pass
	
	def user_leave(self, userId=None, roomId=None, thread=None):
		pass
	
	def user_enter(self, userId=None, roomId=None, thread=None):
		pass
	
	def log(self, msg, silent=False):
		try:
			if silent == False:
				print(msg)
			with open('vrpresence.log','a') as f:
				f.write(str(msg, 'utf-8')+'\n')
		except:
			pass