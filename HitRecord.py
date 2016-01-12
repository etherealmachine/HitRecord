import difflib
import os
import sublime, sublime_plugin
import subprocess
import tempfile


class HitRecordCommand(sublime_plugin.TextCommand):

	recording = None
	paused = False

	def run(self, edit, start=False, stop=False, toggle_pause=False):
		if start:
			self.start()
		elif stop:
			self.stop()
		elif toggle_pause:
			self.toggle_pause()

	def start(self):
		if HitRecordCommand.recording:
			HitRecordCommand.recording.close()
		HitRecordCommand.recording = Recording(self.view)
		HitRecordCommand.paused = False
		sublime.status_message('recording')

	def stop(self):
		if HitRecordCommand.recording:
			HitRecordCommand.recording.close()
			HitRecordCommand.recording = None
		sublime.status_message('recording stopped')

	def toggle_pause(self):
		if HitRecordCommand.paused:
			HitRecordCommand.paused = False
			sublime.status_message('recording')
		else:
			HitRecordCommand.paused = True
			sublime.status_message('recording paused')

	def on_post_save(view):
		if (HitRecordCommand.recording and
			  not HitRecordCommand.paused and
			  HitRecordCommand.recording.view == view):
			HitRecordCommand.recording.checkpoint()

	def on_close(view):
		if (HitRecordCommand.recording and
			  HitRecordCommand.recording.view == view):
			HitRecordCommand.recording.close()


class ViewRecordingCommand(sublime_plugin.TextCommand):

	def run(self, edit):
		if not HitRecordCommand.recording:
			sublime.error_message('no recording found')
			return
		self.view.window().open_file(HitRecordCommand.recording.fname)


class Listener(sublime_plugin.EventListener):
	
	def on_post_save(self, view):
		HitRecordCommand.on_post_save(view)

	def on_close(self, view):
		HitRecordCommand.on_close(view)


class Recording(object):

	def __init__(self, view):
		self.view = view
		self.fname = Recording.name(self.view)
		self.log = open(self.fname, 'w+')

	def checkpoint(self):
		self.log.write('CHECKPOINT\n')
		self.log.write(self.view.substr(sublime.Region(0, self.view.size())))
		self.log.flush()

	def close(self):
		self.log.close()

	@staticmethod
	def name(view):
		dirname, basename = os.path.split(view.file_name())
		return os.path.expanduser(os.path.join('~', basename+'.rec'))

	@staticmethod
	def load(fname):
		checkpoints = []
		with open(fname, 'r') as f:
			lines = []
			for line in f:
				if line == 'CHECKPOINT\n':
					checkpoints.append(''.join(lines))
					lines = []
				else:
					lines.append(line)
			if lines:
				checkpoints.append(''.join(lines))
		return checkpoints


class PlaybackRecordingCommand(sublime_plugin.TextCommand):

	ops = None
	count = 0

	def run(self, edit, clear=False):
		if clear:
			PlaybackRecordingCommand.ops = None
		elif not PlaybackRecordingCommand.ops:
			self.view.erase(edit, sublime.Region(0, self.view.size()))
			PlaybackRecordingCommand.ops = genops(Recording.load(Recording.name(self.view)))
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
				elif optype == 'command':
					settings = sublime.load_settings('HitRecord.sublime-settings')
					ttyecho = settings.get('ttyecho')
					if ttyecho:
						tty = settings.get('tty')
						cmd = opargs['cmd']
						if subprocess.call([ttyecho, '-n', tty, cmd], shell=True):
							sublime.error_message('command failed: ' + cmd)
					else:
						print('ignoring command: no ttyecho set')
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