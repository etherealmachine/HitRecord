import sys
dist_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, dist_dir)

import json
import os
import sublime, sublime_plugin
import time
import diff_match_patch

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

	checkpoint_gen = None

	def run(self, edit, next=False, clear=False, buf=None):
		if buf:
			self.view.erase(edit, sublime.Region(0, self.view.size()))
			changes = []
			with open(os.path.join(os.path.dirname(self.view.file_name()), buf), 'r') as f:
				for line in f:
					changes.append(json.loads(line))
			PlaybackRecordingCommandcheckpoint_gen = gencheckpoints(changes)
		elif clear:
			PlaybackRecordingCommandcheckpoint_gen = None
		elif next:
			try:
				ops = checkpoint_gen.next()
				optype, opargs = ops.next()
				if optype == 'insert':
					self.view.insert(edit, opargs['point'], opargs['text'])
			except StopIteration:
				print('done')
				pass
		#sublime.set_timeout_async(lambda: self.view.run_command('exec_command', {'command': command}), 1000)

def gencheckpoints(changes):
	for change in changes:
		yield genops(change)

def genops(change):
	differ = diff_match_patch.diff_match_patch()
	diff = differ.diff_main(change['oldState'], change['newState'])
	point = 0
	for (diff_type, text) in diff:
		if diff_type == differ.DIFF_EQUAL:
			point += len(text)
		elif diff_type == differ.DIFF_INSERT:
			yield ('insert', {'point': point, 'text': text})
		elif diff_type == differ.DIFF_DELETE:
			continue

class ChangeBuffer(object):

	def __init__(self, view):
		self.view = view
		self.target = view.file_name()
		self.ts = time.time()
		self.state = view.substr(sublime.Region(0, view.size()))
		self.logfile = open(
			os.path.join(
				os.path.dirname(self.target),
				os.path.basename(self.target) + '.rec'), 'w')

	def checkpoint(self, newState):
		print('checkpoint')
		change = {
			'oldState': self.state,
			'newState': newState,
			'deltat': time.time() - self.ts
		}
		self.logfile.write(json.dumps(change))
		self.logfile.write('\n')
		self.logfile.flush()
		self.state = newState

	def add_change(self, change):
		self.ts = time.time()
		self.changes.append(change)

	def update_state(self, newState):
		change = transform(self.state, newState)
		if not change:
			return
		self.add_change(change)
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