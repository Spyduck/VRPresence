
class addon():
	def __init__(self):
		print('test_module Addon initialized')
	
	def user_chat(self, userId, message):
		self.log(userId+': '+message)
	
	def log(self, msg, silent=False):
		try:
			if silent == False:
				print(msg)
			with open('vrpresence.log','a') as f:
				f.write(str(msg, 'utf-8')+'\n')
		except:
			pass