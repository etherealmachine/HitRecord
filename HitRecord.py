import os, sys
dist_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, dist_dir)

import diff_match_patch
import json
import sublime, sublime_plugin

class ToggleRecordingCommand(sublime_plugin.TextCommand):

	recording = False

	def run(self, edit, **args):
		ToggleRecordingCommand.recording = not ToggleRecordingCommand.recording
		if ToggleRecordingCommand.recording:
			print('recording ON')
			if not ChangeRecorder.buf:
				ChangeRecorder.buf = ChangeBuffer(self.view)
			elif ChangeRecorder.buf.target is not self.view.file_name():
				ChangeRecorder.buf.logfile.close()
				ChangeRecorder.buf = ChangeBuffer(self.view)
		if not ToggleRecordingCommand.recording:
			print('recording OFF')
			ChangeRecorder.buf.logfile.close()

class PlaybackRecordingCommand(sublime_plugin.TextCommand):

	ops = None
	count = 0

	def run(self, edit, clear=False):
		if not PlaybackRecordingCommand.ops:
			self.view.erase(edit, sublime.Region(0, self.view.size()))
			changes = []
			with open(os.path.join(os.path.dirname(self.view.file_name()), 'recording'), 'r') as f:
				for line in f:
					changes.append(json.loads(line))
			PlaybackRecordingCommand.ops = gencheckpoints(changes)
			PlaybackRecordingCommand.count = 0
			self.view.run_command('playback_recording')
		elif clear:
			PlaybackRecordingCommand.ops = None
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
				elif optype == 'pause':
					sublime.status_message('?')
					self.view.run_command('exit_insert_mode')
					self.view.run_command('save')
					return
				sublime.set_timeout_async(lambda: self.view.run_command('playback_recording'), 50)
			except StopIteration:
				sublime.status_message('\\o/')
				PlaybackRecordingCommand.ops = None

def gencheckpoints(changes):
	for change in changes:
		for op in genops(change):
			yield op
		yield ('pause', None)

def genops(change):
	differ = diff_match_patch.diff_match_patch()
	diff = differ.diff_main(change['oldState'], change['newState'])
	point = 0
	for (diff_type, text) in diff:
		if diff_type == differ.DIFF_EQUAL:
			point += len(text)
		elif diff_type == differ.DIFF_INSERT:
			if text[-1] == '\n':
				yield ('insert', {'point': point, 'text': '\n'})
				text = text[:-1]
			for i, c in enumerate(text):
				yield ('insert', {'point': point+i, 'text': c})
			point += len(text)
		elif diff_type == differ.DIFF_DELETE:
			continue

class ChangeBuffer(object):

	def __init__(self, view):
		self.view = view
		self.target = view.file_name()
		self.state = view.substr(sublime.Region(0, view.size()))
		self.logfile = open(os.path.join(os.path.dirname(self.target), 'recording'), 'w')

	def checkpoint(self, newState):
		print('checkpoint')
		change = {
			'oldState': self.state,
			'newState': newState
		}
		self.logfile.write(json.dumps(change))
		self.logfile.write('\n')
		self.logfile.flush()
		self.state = newState

class ChangeRecorder(sublime_plugin.EventListener):

	buf = None

	def on_post_save(self, view):
		if not ToggleRecordingCommand.recording:
			return
		if not ChangeRecorder.buf or ChangeRecorder.buf.target != view.file_name():
			return
		newState = view.substr(sublime.Region(0, view.size()))
		ChangeRecorder.buf.checkpoint(newState)