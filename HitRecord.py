import difflib
import os
import sublime, sublime_plugin

class ToggleRecordingCommand(sublime_plugin.TextCommand):

	recording = False

	def run(self, edit, **args):
		ToggleRecordingCommand.recording = not ToggleRecordingCommand.recording
		if ToggleRecordingCommand.recording:
			sublime.status_message('recording')
			if not ChangeRecorder.buf:
				ChangeRecorder.buf = ChangeBuffer(self.view)
			elif ChangeRecorder.buf.view != self.view:
				ChangeRecorder.buf.logfile.close()
				ChangeRecorder.buf = ChangeBuffer(self.view)
		if not ToggleRecordingCommand.recording:
			sublime.status_message('')
			ChangeRecorder.buf.logfile.close()

class PlaybackRecordingCommand(sublime_plugin.TextCommand):

	ops = None
	count = 0

	def run(self, edit, clear=False):
		if clear:
			PlaybackRecordingCommand.ops = None
		elif not PlaybackRecordingCommand.ops:
			self.view.erase(edit, sublime.Region(0, self.view.size()))
			checkpoints = []
			with open(os.path.join(os.path.dirname(self.view.file_name()), 'recording'), 'r') as f:
				lines = []
				for line in f:
					if line == 'CHECKPOINT\n':
						checkpoints.append(''.join(lines))
						lines = []
					else:
						lines.append(line)
				if lines:
					checkpoints.append(''.join(lines))
			PlaybackRecordingCommand.ops = genops(checkpoints)
			PlaybackRecordingCommand.count = 0
			self.view.run_command('playback_recording')
		else:
			self.view.run_command('enter_insert_mode')
			try:
				PlaybackRecordingCommand.count += 1
				if PlaybackRecordingCommand.count % 2 == 0:
					sublime.status_message('/')
				else:
					sublime.status_message('\\')
				optype, opargs = next(PlaybackRecordingCommand.ops)
				if optype == 'insert':
					point, text = opargs['point'], opargs['text']
					self.view.sel().clear()
					self.view.sel().add(sublime.Region(point))
					self.view.insert(edit, point, text)
				elif optype == 'erase':
					point = opargs['point']
					self.view.sel().clear()
					self.view.sel().add(sublime.Region(point))
					self.view.erase(edit, sublime.Region(point, point+1))
				elif optype == 'pause':
					sublime.status_message('?')
					self.view.run_command('exit_insert_mode')
					self.view.run_command('save')
					return
				sublime.set_timeout_async(lambda: self.view.run_command('playback_recording'), 50)
			except StopIteration:
				sublime.status_message('\\o/')
				PlaybackRecordingCommand.ops = None

def genops(checkpoints):
	for i, newState in enumerate(checkpoints[1:]):
		oldState = checkpoints[i]
		diffs = difflib.ndiff(oldState, newState)
		point = 0
		for diff in diffs:
			if diff[:2] == '  ':
				point += 1
			elif diff[:2] == '+ ':
				yield ('insert', {'point': point, 'text': diff[2:]})
				point += 1
			elif diff[:2] == '- ':
				yield ('erase', {'point': point})
		yield ('pause', None)

class ChangeBuffer(object):

	def __init__(self, view):
		self.view = view
		self.logfile = open(os.path.join(os.path.dirname(self.view.file_name()), 'recording'), 'w')

	def checkpoint(self):
		self.logfile.write('CHECKPOINT\n')
		self.logfile.write(self.view.substr(sublime.Region(0, self.view.size())))
		self.logfile.flush()

class ChangeRecorder(sublime_plugin.EventListener):

	buf = None

	def on_post_save(self, view):
		if not ToggleRecordingCommand.recording:
			return
		if view == ChangeRecorder.buf.view:
			ChangeRecorder.buf.checkpoint()