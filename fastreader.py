#!/usr/bin/env python3



import json
from kivy.app import App
from kivy.properties import NumericProperty
from kivy.properties import StringProperty
from kivy.properties import ListProperty
from kivy.properties import ObjectProperty
from kivy.properties import BooleanProperty
from kivy.uix.widget import Widget
from kivy.uix.modalview import ModalView
from kivy.clock import Clock
from kivy.lang import Builder

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.stacklayout import StackLayout

from kivy.uix.filechooser import FileChooserListView
from kivy.uix.filechooser import FileChooserIconView

from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.dropdown import DropDown
from kivy.uix.screenmanager import ScreenManager, Screen

from kivy.uix.tabbedpanel import TabbedPanel

from kivy.utils import escape_markup
from kivy.utils import get_color_from_hex
from kivy.utils import get_hex_from_color

from functools import partial
from enum import Enum
import sys
import re  # #2
import os
from collections import namedtuple
from unicodedata import category as ucategory
from struct import Struct
#from time import sleep
#### ^expunge this! replace sleep

import kivy
from collections import namedtuple
kivy_version = kivy.__version__

## if we want to share these with the kv file,
## we should rename the kv file (to not match app),
## then set these/relevant vars to the App class,
## then instantiate App (app=App()) and set in kv:
## <attr>: app.<var>


default_config_json = """
{
    "data": {
        "12345": {}
    }, 
    "font": "", 
    "gbstyle": true, 
    "maxlen": 8, 
    "speedadjust": 1,
    "colors": {
    	"muted": "222222",
    	"semimuted": "555555",
    	"quotes": "44aa44",
    },
}
"""

### word_struct:
### 	int (I):	char position in text where word starts
### 	byte(B):	length of word in text
### 	int (I):	index of word in sub-word list
### 	byte(B): 	number of subwords (struct elements) for this word
WordTupleStructString = '=IBIB'
WordTuple = namedtuple('Word','char_pos word_len subword_index subword_count')

### subword_struct:
###		int (I): 	char position in text where subword starts
### 	byte(B): 	length of sub-word in text
### 	int (I):	index of word in original-word list
### 	byte(B):	total count of subwords for this word
### 	byte(B): 	flags:
### 					quote color,
### 					italics,
### 					bold,
### 					muted,
### 	byte(B):	weight
ModWordTupleStructString = '=IBIBBB'
ModWordTuple = namedtuple('ModWord','char_pos subword_len word_index subword_count flags weight')

class Formats(Enum):
	PLAINTEXT = 0
	GUTENBERG = 1
	HTML = 2

class WordFlags(Enum):
	FORMAT = 1
	BOLD = 2
	ITALICS = 4
	QUOTES = 8
	#MUTED = 16
	#SEMIMUTED = 32

class Encodings(Enum):
	UTF8 = 1
	UTF16BE = 2
	UTF16LE = 3
	UTF32BE = 4
	UTF32LE = 5
	#{
	#	'\xef\xbb\xbf': 1,
	#	'\xfe\xff': 2,
	#	'\xff\xfe': 3,
	#	'\x00\x00\xfe\xff': 4,
	#	'\xff\xfe\x00\x00': 5,
	#}

def version_check(ver, minver):
	"""returns int:
	-1 ver is less than minver
	0 ver is same as minver
	1 ver is greater than minver
	"""
	if ver == minver:
		return 0
	versions_list = [ver, minver]
	dbg('ver: %s' % ver)
	dbg('minver: %s' % minver)
	versions_list.sort(
		key=lambda s: list(map(
			int,
			re.sub(
				r'[^\d.]','',re.sub(r'-.*',r'',s)
			).split('.')
		))
	)
	if versions_list[0] == ver:
		return -1
	else:
		return 1

#class FileChooserContainer(BoxLayout):
#	TabbedPanel:

class Settings(Widget):
	settings_folder = StringProperty('.')
	docs_folder = StringProperty('.')
	icon_folder = StringProperty()
	newline = StringProperty()
	tabline = StringProperty()
	maxwordlen = NumericProperty()
	color_muted = ListProperty()
	color_semimuted = ListProperty()
	color_quotes = ListProperty()
	hex_muted = StringProperty()
	hex_semimuted = StringProperty()
	hex_quotes = StringProperty()
	sleepbase = NumericProperty(0.08)  # #float/double: for normal words, per char
	sleepab = NumericProperty(0.05)  # #float/double: for abnormal words, per char
	sleepcapitals = NumericProperty(0.03)  # #float/double: for each capital letter
	smallwordlen = NumericProperty(4)  # #uint: small words get same fast pace
	wordlenfactor = NumericProperty(6)  # #? uint
	img_icon_play = StringProperty()
	img_icon_pause = StringProperty()
	img_icon_slower = StringProperty()
	img_icon_faster = StringProperty()
	config_file = StringProperty()
	speed_adjust = StringProperty()

	def __init__(self):
		super(Settings,self).__init__()


class Book(Widget):
	"""
	Holds original words, their modifications and the constructs that contain them.
	Required args:
		@str text
		@Settings settings
	"""
	def __init__(self, text, settings):
		"""

		:param text: string of the entire document to read
		:param settings: ref to settings object
		"""
		self.text = text
		self.settings = settings
		self._detect_encoding()
		## original words are held in text_array
		self.text_array = bytearray()
		self.word_structs = bytearray()
		### word_struct:
		### 	int (I):	char position in text where word starts
		### 	byte(B):	length of word in text
		### 	int (I):	index of word in sub-word list
		### 	byte(B): 	number of subwords (struct elements) for this word
		self.word_struct = Struct(WordTupleStructString)
		#
		### subword_struct:
		###		int (I): 	char position in text where subword starts
		### 	byte(B): 	length of sub-word in text
		### 	int (I):	index of word in original-word list
		### 	byte(B):	length of....something
		### 	byte(B): 	flags:
		### 					quote color,
		### 					italics,
		### 					bold,
		### 					muted,
		### 	byte(B): 	weight
		self.subword_struct = Struct(ModWordTupleStructString)
		self.subword_structs = bytearray()

	def _get_weight(self, subword):
		weight = 10
		for i in subword:
			tmpcat = ucategory(i)
			## lowercase letters
			if tmpcat == 'Ll':
				weight += 2
			## uppercase letters
			elif tmpcat == 'Lu':
				weight += 6
			## digits
			elif tmpcat == 'Nd':
				weight += 6
			## punctuation
			elif tmpcat[0] == 'P':
				weight += 8
			else:
				weight += 10
		return int(weight)

	def _detect_encoding(self):
		"""

		:return: Encodings
		"""
		### TODO: complete and account for different encodings
		if self.text[0] == '\ufeff':
			self._encoding = Encodings.UTF8
		else:
			self._encoding = Encodings.UTF8

	def _get_word_struct_at_index(self,index):
		"""

		:param index:
		:return:
		"""
		return self.word_struct.unpack_from(
			self.word_structs,
			offset=self.word_struct.size * index
		)

	def get_word_at_index(self,index):
		"""

		:param index:
		:return: str
		"""
		str_pos, str_len, subword, sw_count = self._get_word_struct_at_index(index)
		return self.text[str_pos : str_pos + str_len]

	def _get_subword_struct_at_index(self,index):
		"""

		:param index:
		:return: str
		"""
		return self.subword_struct.unpack_from(
			self.subword_structs,
			offset=self.subword_struct.size * index
		)

	def get_subwordf_at_index(self,index):
		"""
		Get partial word and flags at subword index.

		:param index:
		:return: str, byte
		"""
		str_pos, str_len, word, w_count, flags = self._get_subword_struct_at_index(index)
		return self.text[str_pos : str_pos + str_len], flags

	def get_word_count(self):
		"""

		:return: int: word_count
		"""
		return int( len(self.word_structs) / self.word_struct.size )

	def get_subword_count(self):
		"""

		:return: int: subword_count
		"""
		return int( len(self.subword_structs) / self.subword_struct.size )

	def _process_text(self):
		flags = 0
		def _add_to_words(self,subwordlist):
			nonlocal flags
			print('DEBUG: processing word: %s' % repr(subwordlist))
			newflags = flags
			tmpcharpos = subwordlist.pop(0)
			subword_count = len(subwordlist)
			tmpwordlen = len(''.join(subwordlist))
			tmp_wordindex = len(self.word_structs) / self.word_struct.size
			### Word
			### char_pos, word_len, subword_index, subword_count
			print('DEBUG: pack word: %d %d %d %d' % (tmp_charpos, tmpwordlen, self.get_subword_count(), subword_count))
			self.word_structs.extend(
				self.word_struct.pack(tmp_charpos, tmpwordlen, self.get_subword_count(), subword_count)
			)
			wordlen = 0
			for i in range(subword_count):
				tmp_skip = False
				tmpsubword = subwordlist[i]
				tmpsubwordlen = len(tmpsubword)
				tmpweight = self._get_weight(tmpsubword)
				## check for quotes, bold, italics (gutenberg)
				## iff at beginning or end of word
				if subword_count > 1:
					if i == 0:
						if tmpsubword == '"':
							newflags = newflags & WordFlags.QUOTES
						elif tmpsubword == '*':
							newflags = newflags & WordFlags.BOLD
							tmp_skip = True
						elif tmpsubword == '_':
							newflags = newflags & WordFlags.ITALICS
							tmp_skip = True
					elif i == subword_count - 1:
						if tmpsubword == '"':
							newflags = newflags ^ WordFlags.QUOTES
						elif tmpsubword == '*':
							newflags = newflags ^ WordFlags.BOLD
							tmp_skip = True
						elif tmpsubword == '_':
							newflags = newflags ^ WordFlags.ITALICS
							tmp_skip = True

				###
				### char_pos, subword_len, word_index, subword_count, flags, weight
				print('DEBUG: pack subword: %d %d %d %d %d %d' % (
						tmp_charpos,
						len(tmpsubword),
						self.get_word_count(),
						self.get_subword_count(),
						flags,
						self._get_weight(tmpsubword)
				))
				tmpsubarr = self.subword_struct.pack(
						tmp_charpos,
						len(tmpsubword),
						self.get_word_count(),
						self.get_subword_count(),
						flags,
						self._get_weight(tmpsubword)
					) ## asdf asdf asdf
				self.subword_structs.extend(
					tmpsubarr
				)
			flags = newflags

		self._detect_encoding()
		### TODO: remove control/non-printable chars
		#self.text = re.sub(..)
		linelist = self.text.splitlines(True)
		charpos = 0
		wordnum = 0
		subwordnum = 0
		line_charpos = 0
		for linenum in range(len(linelist)):
			words_in_line = 0
			line = linelist[linenum]
			subwordnum = 0
			sublinelist = re.split(r'(\W)',line)
			subwordlist = [line_charpos,]
			tmp_charpos = line_charpos
			found_newline = False
			found_words = False
			while sublinelist:
				tmpelement = sublinelist.pop(0)
				if not tmpelement:
					continue
				elif tmpelement == ' ':
					## process prev subwordlist, new empty word
					if subwordlist:
						_add_to_words(self, subwordlist)
						subwordlist = None
				elif tmpelement == '\t':
					## process prev subwordlist, new word with tab
					if subwordlist:
						_add_to_words(self, subwordlist)
						subwordlist = None

				elif tmpelement == '\n' or tmpelement == '\r':
					## process prev subwordlist, new word with newline if first in line
					if subwordlist:
						_add_to_words(self, subwordlist)
						subwordlist = None
					if not found_newline and not subwordlist_list:
						_add_to_words(self, [tmp_charpos + 1, '\n'])
					subwordlist = None
				else:
					if not subwordlist:
						subwordlist = [tmp_charpos,]
					subwordlist.append(tmpelement)
				tmp_charpos += len(tmpelement)
			if subwordlist:
				_add_to_words(self, subwordlist)
			line_charpos += len(line)


class Reader(Widget):
	"""
	Takes a Book object, passes words to function after delay
	Required args:
	@string filename     file with text to load
	@function callback   should take one arg (string) to update label

	"""
	#word_struct = 'II'
	## ( uint_textcharpos, uint_modwordpos )
	#modword_struct = 'IIBId'
	## ( uint_wordnum, uint_modwordpos, ubyte_wordflags, uint_wordlen, double_wait, )

	percent = NumericProperty()
	word_position = NumericProperty()
	start_italics = BooleanProperty()
	end_italics = BooleanProperty()
	start_bold = BooleanProperty()
	end_bold = BooleanProperty()
	start_quote = BooleanProperty()
	end_quote = BooleanProperty()

	def __init__(
			self,
			settings,
			callback,
			text_format=Formats.GUTENBERG,
	):
		super(Reader, self).__init__()
		## for gutenberg docs...
		## translate _i_ and =b= to italics and bold
		self.settings = settings
		self.text_format = text_format
		self.callback = callback
		#self.maxlen = maxlen
		dbg('\n\n\nReader.__init__()\n\n\n')
		#dbg('maxlen: %s (%s)' % (repr(maxlen), str(type(maxlen))))

		#self.color_muted = '222222'
		#self.color_muted = 'muted'
		#self.color_semimuted = '333333'
		#self.color_semimuted = 'semimuted'
		#self.color_quotes = '44ff44'
		#self.newline = newline if newline else '[color=#%s][b]%s[/b][/color]' % ('_' * maxlen, self.color_muted)
		#self.tabline = tabline if tabline else '[color=#%s][b]_[/b][/color]'
		#self.color_quotes = 'quotes'
		#self.sleepbase = 0.08  # #for normal words, per char
		#self.sleepab = 0.05  # #for abnormal words, per char
		#self.sleepcapitals = 0.03  # #for each capital letter
		#self.smallwordlen = 4  # #small words get same fast pace
		#self.wordlenfactor = 6  # #?
		self.word_position = 0
		self.modword_position = 0
		self.reset_items()
		self.bind(word_position=self.set_percent)

	def reset_items(self):
		self.char_position = 0  # #
		self.speedadjust = self.settings.speed_adjust
		#self.wordlist = []
		self.word_list = []
		self.modword_list = []
		self.italics = False
		self.bold = False
		self.quotes = False
		#self.extended_word = []
		self.percent = 0
		self.total_charcount = 0
		self.total_wordcount = 0
		self.total_modwordcount = 0
		#self.bold = '\x01'
		#self.italics = '\x02'
		self.word_position = 0
		self.modword_position = 0
		self.char_position = 0
		self.set_percent()

	def load_text(self, text):
		self.text = text
		#with open(filename, 'r') as filey:
		#	self.text = filey.read()
		#
		## add an extra space before all non-space whitespace
		## makes it easier to parse it out later (and then not
		## add one to the char count)
		dbg('\n\n\nReader.load()\n\n\n')
		self.reset_count()
		#self.wordlist = re.split(
		#	' ',
		#	re.sub(r'([\n\r\v\f\t])',r' \1 ',
		#		   self.text)
		#)
		## was: '([\t\n\r\f\v]|(?<!\d)[,.]|[,.](?!\d))| '
		self._convert_text()
		self.total_charcount = len(self.text)
		self.total_wordcount = len(self.word_list)
		self.total_modwordcount = len(self.modword_list)
		#
		### XXX DEBUG DELME
		with open('/tmp/modword_list.txt','w') as filey:
			filey.write(repr(self.modword_list))
		### XXX DEBUG DELME
		with open('/tmp/tryme.json','w') as filey:
			json.dump(
				{
					'modword_list':self.modword_list,
					'word_list':self.word_list,
					'text':self.text,
					'newline': self.orig_newline,
					'linepos_list': self.linepos_list,
					'colors': {
						'muted': '222222',
						'semimuted': '333333',
						'quotes': '44ff44'
					}
				},
				filey,)#
			#	indent=4,
			#	sort_keys=True
			#)

		# # remove continuation lines
		#newtext = re.sub(r'([a-z])-\n([a-z])', r'\1\2', newtext)
		#newtext = re.sub(r'\n', r' \n ', newtext)
		#newtext = re.sub(r'\r', '', newtext)
		#
		#self.wordlist = self.text.split(' ')
		#for i in newtext.split(' '):
		#	self.setword(i)

	def start(self):
		self.setword_callback(0)

	def stop(self):
		Clock.unschedule(self.setword_callback)

	def slower(self):
		## increase time between words
		self.speedadjust *= 1.1

	def faster(self):
		## decrease time between words
		self.speedadjust /= 1.1

	def reset_count(self):
		self.word_position = 0
		self.modword_position = 0
		self.char_position = 0
		if self.total_modwordcount:
			self.set_percent()

	def _pad(self, word):
		return '%s%s' % (' ' * (self.settings.maxlen - len(word)), word)

	def _get_linesep(self):
		nl_count = self.text.count('\n')
		cr_count = self.text.count('\r')
		if not nl_count and not cr_count:
			return
		elif not nl_count:
			return '\r'
		elif not cr_count:
			return '\n'
		if nl_count == cr_count:
			##some apps auto do cr AND nl for each line break
			## we want only one line printed in that case
			nlcr_count = self.text.count('\n\r')
			crnl_count = self.text.count('\r\n')
			if nlcr_count > crnl_count and nlcr_count == nl_count:
				return '\n\r'
			elif crnl_count > nlcr_count and crnl_count == nl_count:
				return '\r\n'
			else:
				##this is some weird mixture (manual?) of creturns and newlines
				## convert to newlines, move on...
				text.replace('\r','\n')
				return '\n'

	def _get_tabline(self, pos):
		return self.tabline + ( ' ' * (pos % (self.settings.maxlen - 2))) + self.tabline

	def _colorize_muted(self, word):
		### should only be run after processing major parts of subword
		### and after adding color (which we remove) and escapes
		#
		## remove all color
		newword = re.sub(r'\[color=#[0-9]*\]', r'', word)
		newword = re.sub(r'^',r'[color=#%s]' % self.color_muted, newword)
		newword = re.sub(r'$',r'[/color]', newword)
		return newword
		

	def _render_and_colorize(self, word):
		special = False
		pre_italics = self.italics
		pre_bold = self.bold
		pre_quotes = self.quotes
		### since underline counts as a word-letter \w, we have to
		### do "not-not a word and not an underline" [^\W_] to mean
		### any letter or number. (or for foreign letters if we ever
		### care about foreign locales)

		## by adding color or syntax, we'd be adding letters
		## must know whether REAL letters exist
		hasletters = False
		if self.italics:
			word = '%s%s%s' % ('[i]',word,'[/i]')
		if self.bold:
			word = '%s%s%s' % ('[b]',word,'[/b]')
		if self.quotes:
			word = '%s%s%s' % ('[color=%s]' % self.settings.hex_quotes, word, '[/color]')
		return word
		#if re.findall(r'[\W_]', word):
		#	if re.findall(r'[^\W_]', word):
		#		hasletters = True
		#	special = True
		#	## starter quotes?
		#	if re.findall(r'^[\W_]*".*[^\W_]', word):
		#		word = re.sub(r'(")(.*[^\W_])', r'\1[color=#%s]\2' % self.color_quotes, word)
		#		self.quotes = True
		#	## starter bold?
		#	if re.findall(r'^[\W_]*=.*[^\W_]', word):
		#		word = re.sub(r'^([\W_]*)=(.*[^\W_])', r'\1[b]\2', word)
		#		self.bold = True
		#	## starter italics?
		#	if re.findall(r'^[\W]*_.*[^\W_]', word):
		#		word = re.sub(r'^([\W]*)_(.*[^\W_])', r'\1[i]\2', word)
		#		self.italics = True
		#	## ender quotes?
		#	##   this one might be tough. easy to conflict with beginning
		#	##    quotes if they come AFTER any syntax
		#	if hasletters and self.quotes and re.findall(r'[^\W_](?:[!?._=-]*|\[[^\]]*\])*"[\W_]*$', word):
		#		#word = re.sub(r'[^\W_](?:[!?._=-]*|\[[^\]]*\])*"[\W_]*$', r'\1[/color]\2', word)
		#		### just let the new label unset it?
		#		self.quotes = False
		#	## ender bold?
		#	if hasletters and self.bold  and re.findall(r'[^\W_](?:[!?._=-]*|\[[^\]]*\])*=[\W_]*$', word):
		#		#word = re.sub(r'[^\W_](?:[!?._=-]*|\[[^\]]*\])*"[\W_]*$', r'\1[/color]\2', word)
		#		self.bold = False
		#	## ender italics?
		#	if hasletters and self.italics and re.findall(r'[^\W_](?:[!?._=-]*|\[[^\]]*\])*_[\W_]*$', word):
		#		#word = ....
		#		self.italics = False
		### we do the obligatory starters last so they don't interfere with our regex
		#if pre_italics:
		#	word = re.sub(r'^', r'[i]', word)
		#	if not self.italics:
		#		word += '[/i]'
		#if pre_bold:
		#	word = re.sub(r'^', r'[b]', word)
		#	if not self.bold:
		#		word += '[/b]'
		#if pre_quotes:
		#	word = re.sub(r'^', r'[color=#%s]' % self.color_quotes, word)
		#	if not self.quotes:
		#		word += '[/color]'
		#if special:
		#	##quotes?
		#	if re.findall(r'".*\w', word


	def _convert_text(self):
		newline = self._get_linesep()
		#dbg('newline: %s' % repr(newline))
		self.orig_newline = newline
		newline_len = len(newline)
		#if self.gbstyle:
		#	newline = newline * 2

		### word_list: primarily original content and placemarkers (for certain funcs)
		### modword_list: what gets shown on screen and for how long
		word_list = [] # # contains tuples: (original-word,mod-word-index,char-position)
		### word_list should be the same length no matter how sub-words, newlines, etc
		###  are parsed. It should also provide indexing so that the slider knows what
		###  mod-word to display and a search what character count this would be at.
		modword_list = [] # # contains tuples: (mod-word,original-word-index,wait-interval)
		### modword_list contains direct renderings of each part of a word displayed
		### For each one original-word, it may be split into multiple mod-words based
		###  on length, punctuation, etc.
		### It also has the index of its relevant original-word (also
		###  useful for knowing how far we are even while traversing sub-words)
		###  and how long to wait before showing the next mod-word.
		## 
		charpos = 0
		lines = self.text.split(newline)
		modpos = 0
		origpos = 0
		self.linepos_list = [(0,0),] ## [ (char_pos, word_pos), ]
		#re_wordsplit = re.compile(r'([\s]|[^\W_=]{1,' + \
		#							 str(self.maxlen) + \
		#							 '}-*)'
		#						  )

		### lines will have additional weirdness besides spaces
		### for now, just seperate the tabs, other non-spaces space
		#re_whitespace_split = re.compile(r'([^\S ])')
		#re_wordsplit1 = re.compile(r'(.{8}')
		for orig_line in lines:
			charpos = -1
			### charpos resets each line
			### start at -1 because we add one before each word for a space
			### even if word starts at beginning of line
			### add_to_linepos_list will calculate added offset for line

			line = re.sub(r'[\n\r]', ' ', orig_line)
			if self.word_list and (not line or not self.format == Formats.GUTENBERG):
				## gutenberg style only shows newline after double nl
				self.add_to_modword_list(
					self.newline,
					self.calc_wait('\n')
				)
				#modword_list.append(self.newline)
				charpos += newline_len
				## like new para, so reset all syntax
				self.italics = False
				self.quotes = False
				self.bold = False
				continue
			tabpos = 0
			### for any newlines that aren't part of the split before
			### mainly for gbstyle (which requires double newline to
			### cause a newline display)

			words = re.split('([^\S\w])',line)
			## multiple spaces will make 0-len strs, ignore them


			for word in words:
				charpos += 1
				#dbg('word: %s' % word)
				if not word:
					continue
				elif word == ' ' or word == '\n' or word == '\r' or word == '\f':
					charpos += 1
					continue
				elif word == '\t' or word == '\v':
					self.add_to_word_list('\t', charpos)
					self.add_to_modword_list(
						self.get_tabline(tabpos),
						self.calc_wait('\t')
					)
					charpos += 1
					tabpos += 1
				elif not len(word) > self.settings.maxlen and not re.findall(r'[\W_]', word):
					## normal sized/type word, no special sub-word stuff, no special chars
					self.add_to_word_list(word, charpos)
					self.add_to_modword_list(self._render_and_colorize(word), self.calc_wait(word))
					charpos += len(word)
				else:
					self.add_to_word_list(word, charpos)
					############################################3asdfasdfadsfadsfadsf
					#subwords = [ word[i:i+self.maxlen] \
					#			 for i in range(0, len(word), self.maxlen) \
					#]
					#### split at near maxlen or at any special char
					#### each word will be split into a [<before>,<word>,<after>
					#### then we'll put muted text (before,after) to show progression of word...

					subwords = [ x for x in
								 re.split(
									 r'([\W_]|[^\W_]{%d})' % (self.maxlen - 2,),
									 word
								 )
								 if x
					]
					#wordwaits = [self.calc_wait(x) for x in subwords]
					minwordpos = -1
					maxwordpos = -1
					### find where alphanumerics start/end
					#if re.findall(r'[^\W_]', word):
					#	hasletters = True
					#	for i in range(len(subwords)):
					#		if re.findall(r'[\W_]', subwords[i]):
					#			if minwordpos == -1:
					#				minwordpos = i
					#			maxwordpos = i

					startitalics = []
					enditalics = []
					startquotes = []
					endquotes = []
					startbold = []
					endbold = []
					### TIME TO REPLACE GB FORMATTING!
					for i in range(len(subwords)):
						tmpword = escape_markup(subwords[i])
						tmpnewword = tmpword
						if tmpword == '"':
							if i < len(subwords) - 1 and \
							   re.findall(r'[-_=]*[^\W_]', ''.join(subwords[i+1:])):
								#dbg('  startquotes: %d' % i)
								startquotes.append(i)
							elif i > 0 and \
								 re.findall(r'[^\W_]', ''.join(subwords[:i])):
								#dbg('  endquotes: %d' % i)
								endquotes.append(i)
						elif tmpword == '_':
							#dbg('ITALICS: %d' % i )
							### starting italics?
							### must not be last letter, precede a letter, not be between letters
							if i < len(subwords) - 1 and re.findall(r'[^\W_]', subwords[i+1][0]):
								if i == 0 or not re.findall(r'[^\W_]', subwords[i-1][-1]):
									subwords[i] = ''
									startitalics.append(i)
									#dbg('  startitalics: %d' % i)
							### ending italics?
							### must not be first letter, must follow a letter, not be between letters
							### unfortunately, it MIGHT come after punctuation...
							elif i > 0 and re.findall(
									r'[^\W_][.?!-]*$',
									''.join(subwords[:i])
							):
								if i == len(subwords) - 1 or not re.findall(r'[^\W_]', subwords[i+1][0]):
									subwords[i] = ''
									enditalics.append(i)
									#dbg('  enditalics: %d' % i )
						elif tmpword == '=':
							#dbg('BOLD: %d' % i)
							### starting bold?
							### must not be last letter, precede a letter, not be between letters
							if i < len(subwords) - 1 and re.findall(r'[^\W_]', subwords[i+1][0]):
								if i == 0 or not re.findall(r'[^\W_]', subwords[i-1][-1]):
									subwords[i] = ''
									startbold.append(i)
									#dbg('  startbold: %d' % i)
							### ending bold?
							### must not be first letter, must follow a letter, not be between letters
							elif i > 0 and re.findall(
										r'[^\W_]',
										''.join(subwords[:i])
							):
								if i == len(subwords) - 1 or not re.findall(r'[^\W_]', subwords[i+1][0]):
									subwords[i] = ''
									endbold.append(i)
									#dbg('  endbold: %d' % i )
					#dbg('subwords: %s' % repr(subwords))
					#dbg('  startitalics: %s' % repr(startitalics))
					#dbg('  enditalics: %s' % repr(enditalics))
					#dbg('  startquotes: %s' % repr(startquotes))
					#dbg('  endqutes: %s' % repr(endquotes))

					for i in range(len(subwords)):
						tmpword = escape_markup(subwords[i])
						if not tmpword:
							if startbold.count(i) > 0:
								self.bold = True
							elif endbold.count(i) > 0:
								self.bold = False
							elif startitalics.count(i) > 0:
								self.italics = True
							elif enditalics.count(i) > 0:
								self.italics = False
							continue
						elif tmpword == '"':
							if startquotes.count(i) > 0:
								#dbg('quotes:True: %d' % i)
								self._render_and_colorize(tmpword)
								self.quotes = True
								tmpnewword = tmpword
							elif endquotes.count(i) > 0:
								#dbg('quotes:False: %d' % i)
								self.quotes = False
								tmpnewword = self._render_and_colorize(tmpword)
							else:
								tmpnewword = tmpword
						else:
							tmpnewword = self._render_and_colorize(tmpword)
						if i == 0:
							preword = ''
						else:
							preword = ''.join(subwords[:i])
						if i < (len(subwords) - 1):
							postword = ''.join(subwords[i+1:])
						else:
							postword = ''
						if len(preword) + len(postword) + len(tmpword) > self.settings.maxlen:
							##shorten subword to fit in maxlen field
							if len(preword) > 1:
								if postword:
									preword = preword[-1]
								else:
									preword_len = self.settings.maxlen - len(tmpword)
									preword = preword[-preword_len:]
							postword_len = self.settings.maxlen - (len(preword) + len(tmpword))
							postword = postword[:postword_len]
						#if tmpword == '.' or tmpword == '-' or tmpword == '_' \
						#   or tmpword == '?' or tmpword == '!':
						#	newwait = self.calc_wait(tmpword)
						#else:
						#	newwait = self.calc_wait(preword+tmpword+postword)
						if len(tmpword) == 1:
							newwait = self.calc_wait(tmpword)
						else:
							newwait = self.calc_wait(preword[-2:] + tmpword + postword[:2])
						if preword:
							preword = self._colorize_muted(preword)
						if postword:
							postword = self._colorize_muted(postword)
						self.add_to_modword_list(
							preword + \
							tmpnewword + \
							postword,
							newwait
						)
					charpos += len(word)				

			if self.word_list:
				### kinda cheating, but we're doing the next lines line_pos now
				self.add_to_linepos_list(orig_line)
				#self.linepos_list.append( (len(orig_line) + newline_len, len(words)) )

	def add_to_linepos_list(self, line):
		last_charpos = self.linepos_list[-1][0]
		last_wordpos = self.linepos_list[-1][1]
		self.linepos_list.append( [
			last_charpos + len(self.orig_newline) + len(line),
			len(self.word_list)
			]
		)

	def add_to_word_list(self, text, char_pos):
		"""
		word_list is the un-formatted original text, not what is displayed on screen
		This should be run on a word BEFORE its derived, formatted words
		are added with add_to_modword_list.
		IF add_to_modword_list is NOT run after this, then this will point past the
		end of the modword_list (so please don't let that happen).
		params:
		@str    text         the original text
		@int    char_pos     location (in chars) of word in original text
		"""
		char_pos = int(char_pos)
		assert type(text) is str
		assert type(char_pos) is int
		assert char_pos < len(self.text)
		self.word_list.append(
			(
				text,
				len(self.modword_list),
				char_pos + self.linepos_list[-1][0]
			)
		)

	def add_to_modword_list(self, text, wait):
		"""
		modword_list is what directly displays on screen (with formatting)
		(it is NOT the original word/line)
		This should be run on formatted (sub-)words AFTER its original word
		has been added with add_to_word_list.
		params:
		@str   text         the formatted text
		@float wait         how long before displaying next in list
		"""
		wait = float(wait)
		assert type(text) is str
		assert type(wait) is float
		self.modword_list.append( (text, len(self.word_list) - 1, wait) )
				

	#def convert_word(self, word):
	#	"""
	#	called by setword_callback as needed.
	#	puts long/special words into multi-word segments.
	#	"""
	#	if not word:
	#		return
	#	if len(word) <= self.maxlen:
	#		return
	#	dbg('converting: %s' % word)
	#	self.extended_word = [ \
	#					  x for x in \
	#					  re.split(
	#						  r'(^[=_]|[!.?]|'
	#						  '[\n\t\v\f]|"|[=_]$)',
	#						  bla
	#					  ) if x]
	#	
	#	startitalics = ''
	#	enditalics = ''
	#	startbold = ''
	#	endbold = ''
	#	if self.gbstyle:
	#		if word[0] == '_':
	#			##italics
	#			startitalics = self.italics
	#			self.italics = True
	#		elif word[0] == '=':
	#			##bold
	#			startbold = self.bold
	#			self.bold = True
	#		if word[-1] == '=' and self.bold:
	#			endbold = self.bold
	#			self.bold = False
	#		elif word[-1] == '_' and self.italics:
	#			enditalics = self.italics
	#			self.italics = False
	#	self.extended_word = \
	#		[
	#			startitalics + \
	#			startbold + \
	#			word[i:i+self.maxlen] + \
	#			enditalics + \
	#			endbold \
	#			for i in range(0, len(word), self.maxlen) \
	#		]
	#	lastword = self.extended_word[-1]
	#	end = lastword[-1]
	#	if end == '!' or end == '.' or end == '?':
	#		self.extended_word.append(' ' * (len(lastword)-1)+end)
	#	## since these are word segments, add hyphen
	#	for i in range(0,len(self.extended_word)-1):
	#		if i == 0:
	#			self.extended_word[i] += ' '
	#		else:
	#			self.extended_word[i] += '-'
	#		self.extended_word[i] = self._pad(self.extended_word[i])
	#	self.extended_word.reverse()
	#	## must pop the first from the back (reduce n-time to cost of reverse)
	#	dbg(repr(self.extended_word)) ### asdfasdfasdfdsaf xxx

	def calc_wait(self, word):
		if not word:
			return self.sleepab
		if len(word) == 1 and re.findall(r'\W', word):
			if word == ':' or word == '"':
				return self.sleepab * 4
			elif word == '\n':
				return self.sleepab * 2
			else:
				return self.sleepab * 3
		sleeptime = self.sleepbase
		if word == self.newline:
			return sleeptime
		wordlen = len(word)
		if wordlen > self.smallwordlen:
			sleeptime += (self.sleepbase / self.wordlenfactor) \
						 * (wordlen - self.smallwordlen)
		sleeptime += self.sleepcapitals * len(re.findall(r'[A-Z]', word))
		sleeptime += self.sleepab * len(re.findall(r'[^a-zA-Z]', word))
		## speedadjust will be added when playing
		return sleeptime # #* self.speedadjust

	#def process_special_whitespace(self, word, continuing=True):
	#	## this should cover any whitespace that isn't a space
	#	## not that all these have a redundant space added before them for splitz
	#	dbg("special_whitespace: %s" % word)
	#	if not word:
	#		return False
	#	if word == '\n' or word == '\r':
	#		self.callback(self.newline, escape=False)
	#		self.char_position += 1
	#		self.word_position += 1
	#		if continuing:
	#			Clock.schedule_once(self.setword_callback, self.calc_wait(word))
	#		return True
	#	if word == '\t' or word == '\v' or word == '\f':
	#		calc_wait = self.calc_wait('a')
	#		dbg('tab; pos: %d' % self.tabbed_pos)
	#		self.callback(self.tabline + ' ' * self.tabbed_pos + self.tabline, escape=False)
	#		self.tabbed_pos += 1
	#		if self.tabbed_pos >= self.maxlen:
	#			self.tabbed_pos = 0
	#		self.char_position += 1
	#		self.word_position += 1
	#		if continuing:
	#			Clock.schedule_once(self.setword_callback, calc_wait)
	#		return True
	#	else:
	#		self.tabbed_pos = 0
	#	return False

	def setword_at_percent(self, percent):
		## puts whatever is under current pos into callback
		## right now, just used by slider (while paused)
		## unlike setword_callback, should not proceed to next word
		## will be called by bookmarks
		#dbg('setword_at_percent: %d' % percent)
		if percent >= 100:
			self.callback(None)
			#self.reset_count()
			return
		tmppos = self.total_modwordcount * percent / 100
		if tmppos >= self.total_modwordcount:
			tmppos = self.total_modwordcount - 1
		self.modword_position = int(tmppos)
		#dbg('setword_at_percent: pos: %d of %d' % (self.modword_position,self.total_modwordcount))
		self.setword(continuing=False)

	def get_percent(self):
		## will be called by bookmarks
		return self.percent # # redundant?

	def set_percent(self, *args):
		#dbg('set_percent( %s' % repr(args))
		if self.total_modwordcount <= 0:
			self.percent = 0
		else:
			self.percent = ( 100 * self.modword_position ) / self.total_modwordcount

	def setword_callback(self, dt, *args, **kwargs):
		## maybe we can do this better
		## right now percent is kivy Property, word_position is not
		## playing causes setword_callback to set percent from word_position
		## so is there a gap where percent is wrong?
		## is percent only needed by progbar?
		self.set_percent()
		self.setword(continuing=True)

	def setword(self, continuing=True, **kwargs):
		if self.modword_position >= len(self.modword_list):
			dbg('END')
			self.callback(None)
			#self.char_position = 0
			#self.word_position = 0
			#self.modword_position = 0
			return
		modlist = self.modword_list[self.modword_position]
		newmodword = modlist[0]
		neworigindex = modlist[1]
		newwait = modlist[2]
		self.callback(newmodword)
		if continuing:
			self.modword_position += 1
			if self.modword_position < len(self.modword_list):
				self.word_position = self.modword_list[self.modword_position][1]
			### otherwise, it will trigger the None callback above
			Clock.schedule_once(self.setword_callback, newwait * self.speedadjust)
		###### WOW! we redid all of this... again...
		## called during normal playback
		## like setword, except auto progress to next word
		#if self.extended_word:
		#	## continuing a previous ext word
		#	tmpword = self.extended_word.pop()
		#	if self.process_special_whitespace(tmpword, continuing=continuing):
		#		return
		#	self.callback(tmpword)
		#	if not self.extended_word:
		#		## extended word complete, on to next
		#		self.char_position += len(self.wordlist[self.word_position]) + 1
		#		self.word_position += 1
		#	if continuing:
		#		Clock.schedule_once(self.setword_callback, self.calc_wait(tmpword))
		#	return
		### not an extended word, are we at the end?
		#if self.word_position >= self.total_wordcount:
		#	self.callback(None)
		#	self.char_position = 0
		#	self.word_position = 0
		#	return
		### not an extended word, not the end, load new
		#pos = self.word_position
		#word = self.wordlist[self.word_position]
		#self.convert_word(word)
		#if self.extended_word:
		#	## new word is multi-part
		#	tmpword = self.extended_word.pop()
		#	if self.process_special_whitespace(tmpword, continuing=continuing):
		#		return
		#	self.callback(tmpword)
		#	if not self.extended_word:
		#		## extended word complete? should not be one item long, right?
		#		self.char_position += len(self.wordlist[self.word_position]) + 1
		#		self.word_position += 1
		#	if continuing:
		#		Clock.schedule_once(self.setword_callback, self.calc_wait(tmpword))
		#	return
		#else:
		#	while not word:
		#		## skip 0-len strs
		#		self.char_position += 1
		#		self.word_position += 1
		#		if self.word_position >= self.total_wordcount:
		#			self.callback(None)
		#			return
		#		word = self.wordlist[self.word_position]
		#	if self.process_special_whitespace(word, continuing=continuing):
		#		return
		#	self.callback(word)
		#	self.char_position += len(word) + 1
		#	self.word_position += 1
		#	if continuing:
		#		Clock.schedule_once(self.setword_callback, self.calc_wait(word))
		#	return

			
			

	#def convert_currentword(self):
	#	word = self.current_word
	#	tmplisty = []
	#	#tmplisty.append(word)

	#	tmplisty = re.split('\s|(?<!\d)[,.]|[,.](?!\d)', word)
	#
	#
	#	newtext = word
	#	end = word[-1]
	#	if word == '\n':
	#		return [newline,]
	#	if end == '.':
	#		if re.find(r'[a-z]\.$',word):
	#			tmplisty.append(re.sub(r'.',r' ',word[:-1])+end)
	#	elif end == ',' or end == '!' or end == '?':
	#			tmplisty.append(re.sub(r'.',r' ',word[:-1])+end) 
	#	tmplen = len(tmpword)
	#	if tmpword == '.':
	#		tmpword = '.  .  .'
	#	if tmplen > maxlen:
	#		while tmplen > maxlen:
	#			tmplisty.append(tmpword[:maxlen-1]+'-')
	#			tmpword = tmpword[maxlen-1:]
	#			tmplen = len(tmpword)
	#		if tmpword:
	#			tmplisty.append(tmpword)
	#	else:
	#		tmplisty = [tmpword]
		


def dbg(msg):
	sys.stderr.write(str(msg) + '\n')
	sys.stderr.flush()
	#if sys.version_info.major == 2:
	#	print str(msg)
	#elif sys.version_info.major == 3:
	#	print(str(msg))


#class SettingsWidget(BoxLayout):
#	text = StringProperty('TEXT')
#	fontsize_reg = StringProperty('30sp')
#
#	def __init__(self, text='', fontsize_reg='30sp', **kwargs):
#		super(SettingsWidget, self).__init__(**kwargs)
#		self.fontsize_reg = fontsize_reg
#		self.text = text
#
#
#class SettingsSlider(BoxLayout):
#	def __init__(self, **kwargs):
#		pass
#
#
#class SettingsCheckBox(SettingsWidget):
#	def __init__(self, **kwargs):
#		pass
#
#
#class SettingsSwitch(BoxLayout):
#	pass
#
#
#class SettingsSpinner(BoxLayout):
#	pass
#
#
#class SettingsSpinBox(BoxLayout):
#	pass


class Layout_PopYesNo(BoxLayout):
	bla = StringProperty('class')
	fontsize_reg = StringProperty('400sp')


class Layout_PopMessage(BoxLayout):
	fontsize_reg = StringProperty('400sp')


#class FastReaderWidget(FloatLayout):
class FastReaderScreen(Screen):
	fontsize_reg = StringProperty()
	menu_button_height = NumericProperty()
	menu_button_width = NumericProperty()
	reader = ObjectProperty()
	backup_reader = ObjectProperty()
	isready = BooleanProperty()
	isplaying = BooleanProperty()

	def __init__(self, **kwargs):
		super(FastReaderScreen, self).__init__(**kwargs)
		Clock.schedule_once(self._finish_init)

	def _finish_init(self, *args):
		## init needs to start clock which needs to start this
		## ids/kv-stuff doesn't exist yet in init...
		##  https://stackoverflow.com/questions/26916262/why-cant-i-access-the-screen-ids
		## however, "on_enter"/"on_pre_enter" do not run when first loading default screen
		##  https://github.com/kivy/kivy/issues/2565
		## (didn't explicitly say how to know when "entirely built". wtf.)
		## 
		dbg('_finish_init')
		if self.manager.current is None:
			# #until None changed to '', not completely built, supposedly
			dbg('None: skip')
			Clock.schedule_once(self._finish_init)
			return
		dbg(repr(args))
		#dbg("FastReaderScreen: ids: %s" % repr(self.ids))
		## NOTE: ref.__self__ is THE way to convert weak refs to strong
		##     otherwise, you still risk garbage collection
		progbar = self.ids.progbar.__self__
		progslider = self.ids.progslider.__self__
		menupanel = self.ids.menupanel.__self__
		## dict will hold progbar/slider because we will pop them in and out
		##   will hold menupanel because it was getting garbage collected (why?)
		self.widgetdict = {
			'progbar' : progbar,
			'progslider' : progslider,
			'menupanel' : menupanel,
			}
		self.progbar = progbar
		self.progslider = progslider
		self.menupanel = menupanel
		#self.widgetdict['progbar']
		dbg('mainlayout:kids: %s' % repr(self.ids.mainlayout.children))
		self.ids.mainlayout.remove_widget(progslider)
		self.ids.mainlayout.add_widget(
			progslider,
			index=self.ids.mainlayout.children.index(progbar)
			)
		self.ids.mainlayout.remove_widget(progbar)
		progslider.bind(value=self.update_from_slider)
		self.disable_widget(progslider)
		### load configs?
		#
		self.load_config()
		self.create_reader()
		self.canvas.ask_update()
	#	dbg("AAAAAAAAAA: %s" % repr(self.ids))
	#	self.dropdown = self.ids.menupanel

	def start_first_time(self, firsttime=False, wanthelp=False):
		if firsttime:
			self.popupYesNo('Did you want information about '
							'this program?',
							yes=partial(self.start_first_time,False,True)
							)
		elif wanthelp:
			self.popupMsg('Help not available yet.')
		else:
			self.create_default_config()
			self.popupYesNo('No configuration found.\n'
						'Is this your first time running the program?',
						yes=partial(self.start_first_time,True)
						)

	def create_default_config(self):
		self.config = json.loads(default_config_json)
		try:
			with open(config_file,'w') as filey:
				json.dump(self.config, filey, indent=4, sort_keys=True)
		except Exception as e:
			self.popupMsg('Error!\n'
						  'Failed to write default configuration to file.\n'
						  '\nouput:%s' % str(e)
			)
			raise(e)
		

	def load_config(self):
		try:
			with open(self.manager.config.config_file,'r') as filey:
				config_text = filey.read()
		except IOError as e:
			if e.errno == 2:
				## no file
				self.start_first_time()
			else:
				self.popupMsg(
					'Error!\nFailed to load configuration file!\n'
							  'output:%s' % str(e)
				)
				self.popupMsg('Please fix this issue (or delete the file) '
							  'and start again.'
				)
				raise(e)
		else:
			try:
				self.config = json.loads(config_text)
			except Exception as e:
				self.popupMsg('Error!\nFailed to load configuration file!\n'
							  'output:%s' % str(e))
				self.popupMsg('Your configuration may be corrupt.\n'
							  'Try deleting the file (%s) and trying again.' \
							  % repr(filename))
			else:
				pass
			

	def write_config(self):
		try:
			json.dump(self.config, self.manager.config.config_file, indent=4, sort_keys=True)
		except Exception as e:
			self.popupMsg('Error!\nUnable to write configuration file!\n'
						  'output:%s' % str(e))

	def get_format(self,filename):
		if filename.split('.')[-1] == 'txt':
			return Formats.GUTENBERG
		else:
			#XXX TODO: add other formats (or at least an error popup)
			return Formats.GUTENBERG

	def update_from_slider(self, slider_instance, percent, *args, **kwargs):
		dbg('update_from_slider( %s %s' % (repr(args),repr(kwargs)))
		if not self.isready:
			self.widgetdict['progslider'].disabled = True
			Clock.schedule_once(
				lambda *args: self.enable_widget(self.widgetdict['progslider']),
				3
			)
			self.popupMsg(
				'This slider will be visible whenever playback is paused.\n'
				'To open a new text, click the three lines in the upper-right '
				'and click the folder icon.\n'
				'Once a text is opened, you can quick-scroll to any part of it '
				'using this slider.'
				)
			return
		if self.isplaying:
			self.go_playpause()  #asdf
		self.reader.setword_at_percent( percent )

	def select_menu_item(self, instance, x, *args):
		if x == 'bookmark':
			self.popupMsg("Bookmark:\nnot yet implemented.")
			#root.manager.current = "bookmark"
		elif x == 'openfile':
			self.manager.load_file(self.load_file)
			#self.manager.current = "openfile"
		elif x == 'settings':
			self.manager.current = "settings"
		elif x == 'scratchpad':
			self.manager.current = "scratchpad"
		elif x == 'help':
			self.manager.current = "help"
		elif x == 'about':
			self.manager.current = "about"
		else:
			raise ValueError("unknown menu value: %s" % str(x))

	def disable_widget(self, widget):
		## wait, we should never have ver < 1.8 right?
		if version_check(kivy_version, '1.8') < 0:
			dbg('BAD VERSION')
			pass
		else:
			### ver > 1.8
			dbg('GOOD VERSION')
			widget.disabled = True

	def enable_widget(self, widget):
		## probably redundant. remove?
		## we were going to allow for other ways from prev versions
		## but prev versions break app anyways, so....
		widget.disabled = False

	def hide_widget(self, widget):
		widget.opacity = 0
		self.disable_widget(widget)

	def show_widget(self, widget):
		self.enable_widget(widget)
		widget.opacity = 1

	def create_reader(self):
		self.reader = Reader(self.manager.config, self.update_text)
		self.progbar.unbind()
		self.reader.bind(percent=self.progbar.setter('value'))
		#self.progbar.bind(value=self.reader.setter('percent'))
		#self.ids.text.text = r'[color=#333333][b]Press play![/b][/color]' #asdf
		self.isplaying = False
		self.progslider.value = 0
		self.enable_widget(self.progslider)


	def load_file(self, path, selection):
		"""
		This should normally be called from openfile screen...
		...which gets started by screenmanager.load_file which
		gets called by clicking the openfile icon
		"""
		dbg("fr.load_file: path: %s , selection: %s" % \
			(repr(path),repr(selection)))
		self.manager.current = 'reader'
		self.isready = False
		#self.reader.load('')
		self.isready = False
		if not selection:
			self.popupMsg('ERROR:\nno file selected')
			return
		filey = selection[0]
		dbg(os.stat(filey))  # ## XXX DEBUG
		self.ids.text.text = r'[color=%s][b]Loading...[/b][/color]' % \
							 self.manager.config.hex_semimuted #asdf
		#self.backup_reader = self.current_reader
		#if self.backup_reader:
		#	pass # # asdfasdfasdf unbind progbar
		#self.current_reader = Reader(filey, self.update_text)
		try:
			with open(filey,'r') as ofiley:
				text = ofiley.read()
		except Exception as e:
			self.popupMsg('ERROR:\nUnable to open file %s.\n'
						  '\n(Exception:%s)' % (repr(filey), str(e)))
		else:
			self.reader.load_text(text)
			self.progbar.unbind()
			self.reader.bind(percent=self.progbar.setter('value'))
			#self.progbar.bind(value=self.reader.setter('percent'))
			self.ids.text.text = r'[color=%s][b]Press play![/b][/color]' % self.manager.config.hex_semimuted #asdf
			self.isready = True
			self.isplaying = False
			self.progslider.value = 0
			self.enable_widget(self.progslider)

	def load_scratch(self):
		pass # #TODO

	def update_text(self, text, escape=False):
		if text is None:
			dbg('LABEL:END')
			self.widgetdict['progslider'].value = self.reader.get_percent()
			self.ids.text.text = r'[color=%s][b]End.[/b][/color]' % self.manager.config.hex_semimuted
			self.pause()
		else:
			if escape:
				self.ids.text.text = escape_markup(text)
			else:
				self.ids.text.text = text

	def go_faster(self):
		dbg('faster')
		dbg('popupYesNo')
		if self.isready:
			self.reader.faster()
		else:
			self.manager.popupMsg('No file is loaded\n'
								  'To open a new file, click on the '
								  'three lines in the upper right and '
								  'then click on the folder icon.')			
		#self.manager.popupYesNo(
		#	'THIS is really interesting\nWhat do you think?\n\n'
		#	'And now for a really long string of text that goes '
		#	'on and on and on...\n\n ...and then this...\nend' * 20,
		#	yes=lambda: dbg('\nYES\n'),
		#	no=lambda: dbg('\nNO\n')
		#)

	def go_slower(self):
		dbg('slower')
		if self.isready:
			self.reader.slower()
		else:
			self.manager.popupMsg('No file is loaded\n'
								  'To open a new file, click on the '
								  'three lines in the upper right and '
								  'then click on the folder icon.')

	def play(self):
		dbg('play')
		if self.isplaying:
			return
		if self.reader.percent >= 100:
			self.reader.reset_count()
			return
		self.isplaying = True
		self.disable_widget(self.ids.btn_menuopen)
		self.hide_widget(self.ids.btn_menuopen)
		#self.ids.btn_menuopen.disabled = True
		self.ids.btn_pause_img.source = img_icon_pause
		progbar = self.widgetdict['progbar']
		progslider = self.widgetdict['progslider']
		mainlayout = self.ids.mainlayout
		tmpindex = mainlayout.children.index(progslider)
		dbg('%s %s %s %d' % (repr(progbar),repr(progslider),repr(mainlayout),tmpindex))
		mainlayout.remove_widget(progslider)
		dbg('%s' % repr(self.progbar.__dict__))
		mainlayout.add_widget(self.progbar, tmpindex)
		self.disable_widget(progslider)
		self.reader.start()

	def pause(self):
		dbg('pause')
		if not self.isplaying:
			return
		self.reader.stop()
		self.isplaying = False
		self.enable_widget(self.ids.btn_menuopen)
		self.show_widget(self.ids.btn_menuopen)
		#self.ids.btn_menuopen.disabled = False
		self.ids.btn_pause_img.source = img_icon_play
		progbar = self.widgetdict['progbar']
		progslider = self.widgetdict['progslider']
		mainlayout = self.ids.mainlayout
		tmpindex = mainlayout.children.index(progbar)
		progslider.value = self.reader.get_percent()
		self.enable_widget(progslider)
		mainlayout.remove_widget(progbar)
		mainlayout.add_widget(self.progslider, tmpindex)

	def go_playpause(self):
		dbg('playpause')
		if self.isready:
			if self.isplaying:
				self.pause()
			else:
				self.play()
		else:
			self.manager.popupMsg('No file is loaded\n'
								  'To open a new file, click on the '
								  'three lines in the upper right and '
								  'then click on the folder icon.')

	def add_bookmark(self):
		pass

	def open_file(self):
		pass

	def open_settings(self):
		pass

	def open_scratchpad(self):
		pass

	def open_panel(self):
		########## XXX THIS IS NOT USED
		self.disable_widget(self.ids.btn_menuopen)
		btn = Button()
		#btn.

	def pick_file(self):
		#pause
		self.file_popup.open()

	def popupYesNo(self, msg, yes=None, no=None):
		return self.manager.popupYesNo(msg, yes=yes, no=no)

	def popupMsg(self, msg, on_close=None):
		return self.manager.popupMsg(msg, on_close=on_close)


#### hyper
#sleepover8 = 0.30
#sleepover5 = 0.17
#sleepunder5 = 0.14
#sleepab = 0.03

### fast
#sleepbase = 0.08
#sleepab = 0.05
#sleepcapitals = 0.03
#smallwordlen = 4
#wordlenfactor = 6




#sleepover8 = 0.40
#sleepover5 = 0.22
#sleepunder5 = 0.18
#sleepab = 0.04
#
#### medium
#sleepover8 = 0.
#sleepover5 = 0.22
#sleepunder5 = 0.18
#sleepab = 0.04
#
#
#
#### slow
#sleepover8 = 0.2
#sleepover5 = 0.11
#sleepunder5 = 0.08
#sleepab = 0.02

#def _pad(tmpword):
#  tmplen = len(tmpword)
#  if tmplen > maxlen:
#    raise Exception('word bigger than maxlen: %s' % tmpword)
#  elif tmplen == maxlen:
#    return tmpword
#  else:
#    tmptmpword = ''
#    if (maxlen-tmplen)%2 == 1:
#      tmptmpword += ' '
#    tmptmpword += ' '*((maxlen-tmplen)/2)
#    tmptmpword += tmpword
#    tmptmpword += ' '*((maxlen-tmplen)/2)
#  return tmptmpword
#
#sleepbase = 0.08
#sleepab = 0.02
#sleepcapitals = 0.01
class SettingsScreen(Screen):
	row_height = NumericProperty(3)

	def testswitch(*args):  # ## XXX DEBUG
		dbg('SWITCHED!')
		for i in args:
			dbg(str(i))


class SettingsRow(BoxLayout):
	pass


class OpenFileScreen(Screen):
	multiselect = ObjectProperty(bool)
	selected = ListProperty([])
	path = StringProperty('')
	_default_path = StringProperty(os.path.expanduser('~'))
	_last_path = StringProperty(os.path.expanduser('~'))
	_load_func = None
	_cancel_func = None

	def _set_selection(self, path=None, selection=None):
		## path will be unicode string: pwd
		## selection will be list with one unicode string: full path to file
		dbg("path: %s" % repr(path))
		dbg("selection: %s" % repr(selection))
		self.path = path
		if selection:
			self.selected = selection

	def _load(self):
		if not self.selected:
			return
		if self._load_func and hasattr(self._load_func, '__call__'):
			self._load_func(self.path, self.selected)
		else:
			self._load_default()
		self._last_path = self.path
		for i in (self.ids.list_view_tab, self.ids.icon_view_tab):
			i.selection = []

	def _cancel(self):
		if self._cancel_func and hasattr(self._cancel_func, '__call__'):
			self._cancel_func()
		else:
			self._cancel_default()
		for i in (self.ids.list_view_tab, self.ids.icon_view_tab):
			i.selection = []
			i.path = self._last_path

	def _load_default(self):
		self.manager.current = 'reader'
		self.manager.popupMsg('ERROR:\nFile load not set to an action')

	def _cancel_default(self):
		self.manager.current = 'reader'


class ScratchpadScreen(Screen):
	sample_text = StringProperty(
		'Welcome to FastReader.\n'
		'I hope you enjoy it.\n'
		'If you are new to this kind of '
		'speed-reading, try starting at a '
		'slow speed until you feel comfortable... \n'
		'This particular message is from the ScratchPad.\n'
		'In the ScratchPad, you can paste text '
		'and send it straight to the reader.\n'
		'The ScratchPad and all other resources '
		'are available from the dropdown menu.\n'
		'To reach the dropdown menu, click on '
		'the upper right corner of this screen '
		'while in reading mode.\n'
		'You know you are in reading mode when you '
		'see buttons for "play/pause", "slow" and '
		'"fast-forward"...'
	)
	#scratch_text = StringProperty(self.sample_text)
	def _load(self):
		pass




class HelpScreen(Screen):
	pass


class AboutScreen(Screen):
	pass


class FRScreenManager(ScreenManager):
	menu_button_height = NumericProperty(30)
	menu_button_width = NumericProperty(30)
	row_height = NumericProperty(30)
	fontsize_reg = StringProperty("30sp")
	fontsize_small = StringProperty("20sp")

	def __init__(self, **kwargs):
		super(FRScreenManager, self).__init__(**kwargs)
		self.config = Settings()
		dbg("FRScreenManager IDS: %s" % repr(self.ids))
		dbg("FRScreenManager curr: %s" % repr(self.current))
		dbg("FRScreenManager SCREENS: %s" % repr([Screen(name='Title {}'.format(i)) for i in range(4)]))
#		self.reader = Reader()
		#self.config_popup = ConfigPopup()
		#self.file_popup = FilePopup()
		Clock.schedule_once(self._finish_init)

	def _finish_init(self,*args,**kwargs):
		self.canvas.ask_update()

	def load_file(self, load_func, cancel_func=None, multiselect=False):
		"""
		takes one mandatory and one optional function as arguments
		Opens the file-selection screen. Upon selection, filechooser
		will run the first function provided here. If canceled by user,
		will run the second function (if provided).

		First function must accept two args:
		path:       str(path)
		selection:  list([ str(file),...])
		"""
		if load_func and hasattr(load_func, '__call__'):
			self.get_screen('openfile')._load_func = load_func
		if cancel_func and hasattr(cancel_func, '__call__'):
			self.get_screen('openfile')._cancel_func = cancel_func
		self.current = 'openfile'

	def popupYesNo(self, msg, yes=None, no=None):
		dbg('YesNo started from SCREENMANAGER')
		########################## init Layout_PopYesNo
		layout_yesno = Layout_PopYesNo()
		#layout_yesno.bind(reg_fontsize=self.setter('reg_fontsize'))
		#layout_yesno.ids.message.bind(font_size=self.setter('reg_fontsize'))
		#self.sv.bind(reg_fontsize=self.setter('reg_fontsize'))
		#sv.ids.message.bind(font_size=self.setter('reg_fontsize'))

		#
		############## set message
		layout_yesno.ids['message'].text = str(msg)
		#
		dbg('YesNo msg set')
		#
		#func for clicking yes
		if yes is None:
			func_y = lambda: p.dismiss()
		else:
			assert hasattr(yes, '__call__')
			def func_y(*args):
				dbg('YesNo pressed yes')
				yes()
				p.dismiss()
		##################### set btn_yes
		layout_yesno.ids['btn_yes'].on_release = func_y
		#
		# func for clicking no
		if no is None:
			func_n = lambda: p.dismiss()
		else:
			assert hasattr(no, '__call__')
			def func_n(*args, **kwargs):
				dbg('YesNo pressed no')
				no()
				p.dismiss()
		################### set btn_no
		layout_yesno.ids['btn_no'].on_release = func_n

		p = Popup(
			size_hint=[0.8, 0.8],
			title='FastReader',
			auto_dismiss=False,
			content=layout_yesno
		)
		p.open()
		dbg('YesNo closed')
		return

	def popupMsg(self, msg, on_close=None):
		dbg('PopMessage started from SCREENMANAGER')
		########################## init Layout_PopMessage
		layout_msgclose = Layout_PopMessage()
		#layout_msgclose.bind(reg_fontsize=self.setter('reg_fontsize'))
		#layout_msgclose.ids.message.bind(font_size=self.setter('reg_fontsize'))
		#self.sv.bind(reg_fontsize=self.setter('reg_fontsize'))
		#sv.ids.message.bind(font_size=self.setter('reg_fontsize'))

		#
		############## set message
		layout_msgclose.ids['message'].text = str(msg)
		#
		dbg('MsgClose msg set')
		#
		#func for clicking on_close
		if on_close is None:
			func_y = lambda: p.dismiss()
		else:
			assert hasattr(on_close, '__call__')
			def func_y(*args):
				dbg('MsgClose pressed on_close')
				on_close()
				p.dismiss()
		##################### set btn_close
		layout_msgclose.ids['btn_close'].on_release = func_y
		#
		# func for clicking no
		if on_close is None:
			func_n = lambda: p.dismiss()
		else:
			assert hasattr(on_close, '__call__')
			def func_n(*args, **kwargs):
				dbg('MsgClose pressed no')
				on_close()
				p.dismiss()

		p = Popup(
			size_hint=[0.8, 0.8],
			title='FastReader',
			auto_dismiss=False,
			content=layout_msgclose
		)
		p.open()
		dbg('MsgClose closed')
		return










class FastReaderApp(App):
	"""
	"""
	def build(self):
		#sm = ScreenManager()
		#sm.add_widget(FastReaderScreen(name='reader'))
		#sm.add_widget(SettingsScreen(name='settings'))
		#sm.add_widget(OpenFileScreen(name='openfile'))
		#sm.add_widget(ScratchpadScreen(name='scratchpad'))
		#sm.add_widget(HelpScreen(name='help'))
		#sm.add_widget(AboutScreen(name='about'))
		#sm.current = 'reader'
		#return sm
		#return FastReaderWidget()
		return FRScreenManager()


def main():
	#with open('fastreader.kv', 'r') as filey:
	#	kv_layout_str = filey.read()
	#Builder.load_string(kv_layout_str)
	#Builder.load_file('fastreader.kv')
	############# DO NOT run load_string OR load_file if <app>.kv exists!!!!
	#############   otherwise you will DOUBLE LOAD your widgets
	app = FastReaderApp()
	app.run()


if __name__ == '__main__':
	main()
