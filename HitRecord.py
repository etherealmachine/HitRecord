import difflib
import os
import sublime, sublime_plugin
import subprocess
import tempfile


class HitRecordCommand(sublime_plugin.TextCommand):

	recorder = None
	paused = False

	def run(self, edit, start=False, stop=False, resume=False, toggle_pause=False):
		if start:
			self.start()
		elif stop:
			self.stop()
		elif resume:
			self.resume()
		elif toggle_pause:
			self.toggle_pause()

	def start(self):
		if HitRecordCommand.recorder:
			HitRecordCommand.recorder.close()
		HitRecordCommand.recorder = Recorder(self.view)
		HitRecordCommand.paused = False
		sublime.status_message('recording')

	def stop(self):
		if HitRecordCommand.recorder:
			HitRecordCommand.recorder.close()
			HitRecordCommand.recorder = None
		sublime.status_message('recording stopped')

	def resume(self):
		if not HitRecordCommand.recorder:
			HitRecordCommand.recorder = Recorder(self.view, resume=True)
		sublime.status_message('recording resumed')

	def toggle_pause(self):
		if HitRecordCommand.paused:
			HitRecordCommand.paused = False
			sublime.status_message('recording')
		else:
			HitRecordCommand.paused = True
			sublime.status_message('recording paused')

	def on_post_save(view):
		if (HitRecordCommand.recorder and
			  not HitRecordCommand.paused and
			  HitRecordCommand.recorder.view == view):
			HitRecordCommand.recorder.checkpoint()

	def on_close(view):
		if (HitRecordCommand.recorder and
			  HitRecordCommand.recorder.view == view):
			HitRecordCommand.recorder.close()


class ExecInShellCommand(sublime_plugin.TextCommand):

	def run(self, edit, command=None, record=False):
		if command:
			settings = sublime.load_settings('HitRecord.sublime-settings')
			ttyecho = settings.get('ttyecho')
			if ttyecho:
				tty = settings.get('tty')
				try:
					shell_command = '{} {} "{}"'.format(ttyecho, tty, command)
					output = subprocess.check_output(shell_command, shell=True, stderr=subprocess.STDOUT)
				except subprocess.CalledProcessError as ex:
					print('command "{}" failed: {}'.format(command, ex.output))
				if HitRecordCommand.recorder:
					HitRecordCommand.recorder.command(command)
			else:
				print('ignoring command: no ttyecho set')


class Listener(sublime_plugin.EventListener):
	
	def on_post_save(self, view):
		HitRecordCommand.on_post_save(view)

	def on_close(self, view):
		HitRecordCommand.on_close(view)


class Recorder(object):

	def __init__(self, view, resume=False):
		self.view = view
		self.fname = Recording(self.view).fname
		if resume:
			self.log = open(self.fname, 'a')
		else:
			self.log = open(self.fname, 'w')

	def checkpoint(self):
		self.log.write(self.view.substr(sublime.Region(0, self.view.size())))
		self.log.write('CHECKPOINT\n')
		self.log.flush()

	def command(self, command):
		self.log.write('COMMAND ')
		self.log.write(command)
		self.log.write('\n')
		self.log.flush()

	def close(self):
		self.log.close()


class Recording(object):

	def __init__(self, view):
		dirname, basename = os.path.split(view.file_name())
		self.fname = os.path.expanduser(os.path.join('~', basename+'.rec'))
		self.lines = None

	def load(self):
		with open(self.fname, 'r') as f:
			self.lines = f.readlines()

	def ops(self):
		if not self.lines:
			self.load()
		state = []
		oldState = ''
		for line in self.lines:
			if line.startswith('CHECKPOINT'):
				newState = ''.join(state)
				state = []
				for op in genops(oldState, newState):
					yield op
				oldState = newState
			elif line.startswith('COMMAND'):
				cmd = line[len('COMMAND '):].strip()
				for c in cmd:
					yield ('command', {'cmd': c})
				yield ('command', {'cmd': '\n'})
				yield ('pause', None)
			else:
				state.append(line)


def scanline(diffs):
	if len(diffs) <= 1:
		return None
	for i, curr in enumerate(diffs[1:]):
		prev = diffs[i-1]
		if curr.startswith(' ') and prev == '+ \n':
			return i-1
		if not curr.startswith('+'):
			return None
	return None


def genops(oldState, newState):
	diffs = list(difflib.ndiff(oldState, newState))
	point = 0
	ops = []
	while diffs:
		diff = diffs[0]
		t, c = diff[0], diff[2:]
		if t == ' ':
			diffs.pop(0)
			point += 1
		elif t == '+':
			nl = scanline(diffs)
			if nl:
				ops.append(('insert', {'point': point, 'text': '\n'}))
				for i in range(nl):
					diff = diffs.pop(0)
					t, c = diff[0], diff[2:]
					ops.append(('insert', {'point': point, 'text': c}))
					point += 1
				point += 1
				diffs.pop(0)
			else:
				diffs.pop(0)
				ops.append(('insert', {'point': point, 'text': c}))
				point += 1
		elif t == '-':
			diffs.pop(0)
			ops.append(('erase', {'point': point}))
	ops.append(('pause', None))
	return ops


class PlaybackRecordingCommand(sublime_plugin.TextCommand):

	ops = None
	count = 0

	def run(self, edit, start=False, clear=False):
		if clear:
			PlaybackRecordingCommand.ops = None
		elif start and not PlaybackRecordingCommand.ops:
			self.view.erase(edit, sublime.Region(0, self.view.size()))
			PlaybackRecordingCommand.ops = Recording(self.view).ops()
			PlaybackRecordingCommand.count = 0
			sublime.set_timeout_async(lambda: self.view.run_command('playback_recording'), 3000)
		elif PlaybackRecordingCommand.ops:
			self.view.run_command('enter_insert_mode')
			try:
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
					self.view.run_command('exec_in_shell', {'command': opargs['cmd']})
				PlaybackRecordingCommand.count += 1
				if PlaybackRecordingCommand.count % 2 == 0:
					sublime.status_message('/')
				else:
					sublime.status_message('\\')
				sublime.set_timeout_async(lambda: self.view.run_command('playback_recording'), 100)
			except StopIteration:
				sublime.status_message('\\o/')
				PlaybackRecordingCommand.ops = None
		else:
			sublime.status_message('playback finished')
