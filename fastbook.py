#!/usr/bin/env python3

VERSION = 'alpha-alpha0'

import logging.handlers
import os
import sys
import traceback

## more imports below...

### try to get parent's logger if it exists....
logger = logging.getLogger('fastbook')

import json
import re
from functools import partial
from enum import Enum
from enum import IntFlag
from enum import auto as autoenum
from unicodedata import category as ucategory
from struct import Struct
# from time import sleep
#### ^expunge this! replace sleep

from collections import namedtuple
from hashlib import sha256

logger.info('book module starting')

## if we want to share these with the kv file,
## we should rename the kv file (to not match app),
## then set these/relevant vars to the App class,
## then instantiate App (app=App()) and set in kv:
## <attr>: app.<var>


###


### word_struct:
### 	int (I):	char position in text where word starts
### 	byte(B):	length of word in text
### 	int (I):	index of word in sub-word list
### 	byte(B): 	number of subwords (struct elements) for this word
WordStructString = '=IBIB'
WordTuple = namedtuple('Word', 'char_pos word_len subword_index subword_count')

### subword_struct:
### 	byte(B):	length of subword in text
###     byte(B):    weight
### 	byte(B): 	formatting flags
SubWordStructString = '=BBB'
SubWordTuple = namedtuple('SubWord', 'subword_len weight flags')


class Formats(Enum):
    PLAINTEXT = 0
    GUTENBERG = 1


class WordOutput():
    def __init__(self, word, wordnum, subwords, subword_flags, subword_weights):
        self.word = word
        self.wordnum = wordnum
        self.subwords = subwords
        self.subword_flags = subword_flags
        self.subword_weights = subword_weights


class FormatFlags(IntFlag):
    IGNORE = autoenum()
    SPECIAL = autoenum()
    BOLD = autoenum()
    ITALICS = autoenum()
    QUOTES = autoenum()

class Encodings(Enum):
    UTF8 = 1
    UTF16BE = 2
    UTF16LE = 3
    UTF32BE = 4
    UTF32LE = 5


# {
#	'\xef\xbb\xbf': 1,
#	'\xfe\xff': 2,
#	'\xff\xfe': 3,
#	'\x00\x00\xfe\xff': 4,
#	'\xff\xfe\x00\x00': 5,
# }
ConfTuple = namedtuple('SubWord',
                       'max_subword_len'
                       ' weight_base weight_special weight_uppers weight_numbers'
                       ' weight_subwords weight_punctuation'
                       ' small_word_len weight_extra_char speed_adjust')
#class DefaultSettings():
DefaultConf = ConfTuple(
    max_subword_len=7,
    weight_base=8,  # #float/double: for normal words, per char
    weight_special=12,  # #float/double: for abnormal words, per char
    weight_uppers=7,  # #float/double: for each capital letter
    weight_numbers=12,
    weight_subwords=4,
    weight_punctuation=4,
    small_word_len=3,  # #uint: small words get same fast pace
    weight_extra_char=1,  # #? uint
    speed_adjust=1,
)


class Book():
    """
    Holds original words, their modifications and the constructs that contain them.
    Required args:
        @str text
    """

    def __init__(self,
                 text,
                 conf=DefaultConf,
    ):
        """

        :param text: string of the entire document to read
        """
        dbg('starting Book')
        self.text = text
        self.conf = conf
        self._detect_encoding()
        ## original words are held in text_array
        self.text_array = bytearray()
        ## some items will be created/populated by _process_text()
        self.word_struct = Struct(WordStructString)
        self.subword_struct = Struct(SubWordStructString)
        self.word_structs = bytearray()
        self.subword_structs = bytearray()
        ##
        #self.word_structs = None
        #self.subword_structs = None
        #self.word_struct = None
        #self.subword_struct = None
        ##
        self.max_byte_num = int('ff', 16)
        # # since character pos has to fit in three bytes....
        self.max_int_num = int('ffffffff', 16)
        # # number of bytes to read at a time
        self.max_chunk_size = 100000
        if len(self.text) > self.max_int_num:
            logger.warning('text exceeds max size: %d' % len(self.text))
            logger.warning('trimming text to size: %d' % self.max_int_num)
            self.text = self.text[:self.max_int_num]
        self._process_text()
        ##

    def _get_weight(self, subword):
        #global weight_base
        #global weight_uppers
        #global weight_lowers
        #global weight_abnormal
        #global weight_smallwordlen
        #global weight_wordlenfactor
        ##
        HAS_ABNORMAL = False
        HAS_UPPERS = False
        HAS_LOWERS = False
        HAS_DIGITS = False
        HAS_BASE = False
        weight = 0
        for index in range(len(subword)):
            char = subword[index]
            tmpcat = ucategory(char)
            ## lowercase letters
            if tmpcat == 'Ll':
                if not HAS_BASE:
                    weight += self.conf.weight_base
                    HAS_BASE = True
                if index > self.conf.small_word_len:
                    weight += self.conf.weight_extra_char
                HAS_LOWERS = True
            ## uppercase letters
            elif tmpcat == 'Lu':
                if not HAS_UPPERS:
                    weight += self.conf.weight_uppers
                    HAS_UPPERS = True
                if not HAS_BASE:
                    weight += self.conf.weight_base
                    HAS_BASE = True
                if index > self.conf.small_word_len:
                    weight += self.conf.weight_extra_char
            ## digits
            elif tmpcat == 'Nd':
                weight += self.conf.weight_numbers
                weight += self.conf.weight_extra_char * len(subword)
                return weight
                #HAS_DIGITS = True
            ## punctuation
            elif tmpcat[0] == 'P':
                weight += self.conf.weight_special
                HAS_ABNORMAL = True
            elif tmpcat == 'Cc':
                if subword == self.newline:
                    weight += self.conf.weight_special
                elif subword == '\t':
                    weight += self.conf.weight_special
                else:
                    weight = -1
            else:
                weight += 10
        if weight > self.max_byte_num:
            logger.warning('line exceeded format weight capacity (strlen: %d)' % len(subword))
            weight = self.max_byte_num
        logger.debug('weight: %d' % weight)
        return weight

    def _detect_encoding(self):
        """

        :return: Encodings
        """
        ### TODO: complete and account for different encodings
        if self.text[0] == '\ufeff':
            self._encoding = Encodings.UTF8
        else:
            self._encoding = Encodings.UTF8

    def get_char_pos_at_word_index(self, index):
        """

        :param index: int
        :return: int: character position within text
        """
        return self._get_word_tuple_at_index(index).char_pos

    def get_word_index_at_char_pos(self, pos):
        """

        :param pos: int, character position within text
        :return: int, index of word
        """
        # # binary search
        if pos >= len(self.text):
            logger.error('failed search: char pos outside range: %d' % pos)
            return self.get_word_count() - 1
        upper = self.get_word_count() - 1
        lower = 0
        while (upper - lower) > 1:
            mid = int(lower + ((upper - lower)/2))
            tmp_pos = self._get_word_tuple_at_index(mid).char_pos
            if tmp_pos == pos:
                return mid
            elif tmp_pos < pos:
                lower = mid
            else:
                upper = mid
        return lower

    def _get_word_tuple_at_index(self, index):
        """

        :param index:
        :return:
        """
        return WordTuple(
            *self.word_struct.unpack_from(
                self.word_structs,
                offset=self.word_struct.size * index
            )
        )

    def _get_subword_tuple_at_index(self, index):
        """

        :param index:
        :return:
        """
        return SubWordTuple(
            *self.subword_struct.unpack_from(
                self.subword_structs,
                offset=self.subword_struct.size * index
            )
        )

    def _get_word_at_index(self, index):
        """

        :param index:
        :return: str
        """
        ### not used???;
        tup = self._get_word_tuple_at_index(index)
        return self.text[tup.char_pos: tup.char_pos + tup.word_len]

    def get_word_pack_at_index(self, index):
        """

        :param index: int
        :return: tuple, ((subwords,..), (flags,..), (weights,..))
        """
        if index >= self.get_word_count():
            return None
        word_tup = self._get_word_tuple_at_index(index)
        word_txt = self._get_word_at_index(index)
        subwords = []
        subword_weights = []
        subword_flags = []
        subword_start = 0
        subword_index = word_tup.subword_index
        for i in range(word_tup.subword_count):
            subword_tup = self._get_subword_tuple_at_index(subword_index+i)
            if subword_tup.flags & FormatFlags.IGNORE:
                subword_start += subword_tup.subword_len
                continue
            subword_end = subword_start + subword_tup.subword_len
            subwords.append(word_txt[subword_start:subword_end])
            subword_weights.append(subword_tup.weight)
            subword_flags.append(subword_tup.flags)
            subword_start += subword_tup.subword_len
        return (subwords, subword_flags, subword_weights)

    def get_word_count(self):
        """

        :return: int: word_count
        """
        return int(len(self.word_structs) / self.word_struct.size)

    def get_subword_count(self):
        """

        :return: int: subword_count
        """
        return int(len(self.subword_structs) / self.subword_struct.size)

    def _get_newline(self):
        tmpn = re.search('\n', self.text)
        tmpr = re.search('\r', self.text)
        if tmpn and tmpr:
            if tmpn.start() < tmpr.start():
                self.newline = '\n'
            else:
                self.newline = '\r'
        elif tmpr and not tmpn:
            self.newline = '\r'
        else:
            # # there may or may not actually be any newlines
            self.newline = '\n'

    def _process_text(self):
        flags = 0
        #word_struct = Struct(WordStructString)
        #subword_struct = Struct(SubWordStructString)
        #word_structs = bytearray()
        #subword_structs = bytearray()

        # ############################################
        # # START _add_word_list()
        def _add_word_list():
            nonlocal flags
            nonlocal x_subwordlist
            nonlocal x_subwordlist_t
            nonlocal x_subword_weights
            nonlocal x_subword_start_pos
            nonlocal x_subword_current_pos
            _flags = flags
            _next_flags = _flags
            _x_subword_count = len(x_subwordlist)
            if len(x_subwordlist_t) != _x_subword_count:
                raise ValueError('subword count not matching type count: %d %d (%d)' % \
                                 (_x_subword_count, len(x_subwordlist_t), x_subword_current_pos))
            elif len(x_subword_weights) != _x_subword_count:
                raise ValueError('subword count not matching weights count: %d %d (%d)' % \
                                 (_x_subword_count, len(x_subword_weights), x_subword_current_pos))
            if _x_subword_count > 255:
                logger.warning('subword count too large: %d (%d)' % \
                               (_x_subword_count, x_subword_current_pos))
                x_subwordlist = x_subwordlist[:256]
                _x_subword_count = 255
            _x_total_char_len = len(''.join(x_subwordlist))
            ### Word
            ### char_pos, word_len, subword_index, subword_count
            self.word_structs.extend(
                self.word_struct.pack(
                    x_subword_start_pos,
                    _x_total_char_len,
                    self.get_subword_count(),
                    _x_subword_count,
                )
            )
            for _xi in range(_x_subword_count):
                _tmp_subword = x_subwordlist[_xi]
                _tmp_subword_type = x_subwordlist_t[_xi]
                _tmp_subword_len = len(_tmp_subword)
                _tmp_subword_weight = x_subword_weights[_xi]
                if _tmp_subword_type == '.':
                    # # check/set flags based on symbols
                    if _tmp_subword == '"':
                        if _flags & FormatFlags.QUOTES:
                            # # QUOTES ALREADY SET; check if we unset it
                            # # end-quotes must come after letters/nums
                            # # ...and should not have letters/nums after it
                            if _xi == _x_subword_count - 1:
                                _next_flags &= ~ FormatFlags.QUOTES
                                _flags &= ~ FormatFlags.QUOTES
                            else:
                                _xgood = False
                                for _xj in x_subwordlist_t[:_xi]:
                                    if _xj == 'A' or _xj == 'a' or _xj == '0':
                                        _xgood = True
                                        break
                                # # or maybe let's be greedy with turning off
                                #for _xj in x_subwordlist_t[_xi + 1:]:
                                #    if _xj == 'A' or _xj == 'a' or _xj == '0':
                                #        _xgood = False
                                #        break
                                if _xgood:
                                    _next_flags &= ~ FormatFlags.QUOTES
                                    _flags &= ~ FormatFlags.QUOTES
                        elif _x_subword_count > 1:
                            # # QUOTES NOT YET SET, check if we should set it
                            if _xi == 0:
                                # # beginning of word = good to set
                                _next_flags |= FormatFlags.QUOTES
                            else:
                                # # should have letters/nums after, none before
                                _xgood = False
                                for _xj in x_subwordlist_t[_xi + 1:]:
                                    if _xj == 'A' or _xj == 'a' or _xj == '0':
                                        _xgood = True
                                        break
                                for _xj in x_subwordlist_t[:_xi]:
                                    if _xj == 'A' or _xj == 'a' or _xj == '0':
                                        _xgood = False
                                        break
                                if _xgood:
                                    _next_flags &= ~ FormatFlags.QUOTES
                    elif _tmp_subword == '*':
                        # # toggle BOLD?
                        if _flags & FormatFlags.BOLD:
                            # # BOLD ALREADY SET, check if we should unset it
                            if _xi == _x_subword_count - 1:
                                _flags &= ~ FormatFlags.BOLD
                                _next_flags &= ~ FormatFlags.BOLD
                                _tmp_subword_weight = -1
                            else:
                                _xgood = False
                                for _xj in x_subwordlist_t[:_xi]:
                                    if _xj == 'A' or _xj == 'a' or _xj == '0':
                                        _xgood = True
                                        break
                                # # or let's be greedy on turning off
                                #for _xj in x_subwordlist_t[_xi + 1:]:
                                #    if _xj == 'A' or _xj == 'a' or _xj == '0':
                                #        _xgood = False
                                #        break
                                if _xgood:
                                    _flags &= ~ FormatFlags.BOLD
                                    _next_flags &= ~ FormatFlags.BOLD
                                    _tmp_subword_weight = -1
                        elif _x_subword_count > 1:
                            # # BOLD NOT YET SET, check if we should set it
                            if _xi == 0:
                                # # beginning of word = good to set
                                _flags |= FormatFlags.BOLD
                                _next_flags |= FormatFlags.BOLD
                                _tmp_subword_weight = -1
                            else:
                                # # should have letters/nums after, none before
                                _xgood = False
                                for _xj in x_subwordlist_t[_xi + 1:]:
                                    if _xj == 'A' or _xj == 'a' or _xj == '0':
                                        _xgood = True
                                        break
                                for _xj in x_subwordlist_t[:_xi]:
                                    if _xj == 'A' or _xj == 'a' or _xj == '0':
                                        _xgood = False
                                        break
                                if _xgood:
                                    _flags |= FormatFlags.BOLD
                                    _next_flags |= FormatFlags.BOLD
                                    _tmp_subword_weight = -1
                    elif _tmp_subword == '_':
                        # # toggle ITALICS?
                        if _flags & FormatFlags.ITALICS:
                            # # ITALICS ALREADY SET, check if we should unset it
                            if _xi == _x_subword_count - 1:
                                _flags &= ~ FormatFlags.ITALICS
                                _next_flags &= ~ FormatFlags.ITALICS
                                _tmp_subword_weight = -1
                            else:
                                _xgood = False
                                for _xj in x_subwordlist_t[:_xi]:
                                    if _xj == 'A' or _xj == 'a' or _xj == '0':
                                        _xgood = True
                                        break
                                # # or let's be greedy on turning off
                                #for _xj in x_subwordlist_t[_xi + 1:]:
                                #    if _xj == 'A' or _xj == 'a' or _xj == '0':
                                #        _xgood = False
                                #        break
                                if _xgood:
                                    _flags &= ~ FormatFlags.ITALICS
                                    _next_flags &= ~ FormatFlags.ITALICS
                                    _tmp_subword_weight = -1
                        elif _x_subword_count > 1:
                            # # ITALICS NOT YET SET, check if we should set it
                            if _xi == 0:
                                # # beginning of word = good to set
                                _flags |= FormatFlags.ITALICS
                                _next_flags |= FormatFlags.ITALICS
                                _tmp_subword_weight = -1
                            else:
                                # # should have letters/nums after, none before
                                _xgood = False
                                for _xj in x_subwordlist_t[_xi + 1:]:
                                    if _xj == 'A' or _xj == 'a' or _xj == '0':
                                        _xgood = True
                                        break
                                for _xj in x_subwordlist_t[:_xi]:
                                    if _xj == 'A' or _xj == 'a' or _xj == '0':
                                        _xgood = False
                                        break
                                if _xgood:
                                    _flags |= FormatFlags.ITALICS
                                    _next_flags |= FormatFlags.ITALICS
                                    _tmp_subword_weight = -1
                # # done parsing symbols
                # #  let's do final cleanups/checks/flag-changes and add sub-word
                # # char_pos, subword_len, word_index, subword_count, flags, weight
                if _tmp_subword_weight == -1:
                    _tmpflags = FormatFlags.IGNORE
                    _tmp_subword_weight = 0
                elif _tmp_subword_type == '\t':
                    # # special type
                    if _tmp_subword == self.newline or _tmp_subword == '\t':
                        _tmpflags = FormatFlags.SPECIAL
                        # # if we wanted to reset all flags at a special char, we'd do it here
                        #flags = 0
                    else:
                        _tmpflags = FormatFlags.IGNORE
                else:
                    _tmpflags = _flags
                if _tmp_subword_len > 255:
                    logger.error('subword too long: %d: %d' % \
                                 (x_subword_current_pos, _tmp_subword_len))
                    _tmp_subword_len = 255
                _tmp_subword_weight = int(_tmp_subword_weight)
                if _tmp_subword_weight > 255:
                    logger.error('weight too big: %d: %d' % \
                                 (x_subword_current_pos, _tmp_subword_weight))
                    _tmp_subword_weight = 255
                if _tmpflags > 255:
                    logger.error('flags be crazy: %d: %d' % (x_subword_current_pos, _tmpflags))
                # # make sub-word byte struct
                _tmpsubarr = self.subword_struct.pack(
                    _tmp_subword_len,
                    _tmp_subword_weight,
                    _tmpflags,
                )
                # # add sub-word byte struct
                self.subword_structs.extend(
                    _tmpsubarr
                )
                # # get next_flags set for the next round
                _flags = _next_flags
            # # push values back outside the function
            flags = _flags
            x_subwordlist.clear()
            x_subwordlist_t.clear()
            x_subword_weights.clear()
        # # END _add_word_list()
        # ###################################

        self._detect_encoding()
        # # TODO: something with encoding...?
        self._get_newline()
        x_newline = self.newline
        x_max_subword_len = self.conf.max_subword_len
        x_subword_start_pos = 0
        x_subword_current_pos = 0
        x_re_init_pos = 0
        x_re_offset = self.max_chunk_size
        # # holds actual chunks of current word
        x_subwordlist = []
        # # holds representation of the type of a chunk of current word
        # # A=upper, a=lower, .=punctuation, newline=newline
        x_subwordlist_t = []
        # # weights for each subword
        x_subword_weights = []
        ## read ~100k chars at a time. makes memload smaller during parsing
        while x_re_init_pos < len(self.text):
            subtxt = self.text[x_re_init_pos:x_re_init_pos + x_re_offset]
            logger.debug('len subtxt: %d' % len(subtxt))
            #splitoutlist = re.split('(\W|\w{1,%d})' % self.conf.max_subword_len, subtxt)
            splitoutlist = re.split('(\W|[0-9]+|[^\W_]+|.)', subtxt)
            #splitoutlist = re.split('([0-9]+|[a-zA-Z]+|.)', subtxt)
            for tmpindex in range(len(splitoutlist)):
                subx = splitoutlist[tmpindex]
                if not subx:
                    continue

                cat = ucategory(subx[0])
                if cat[0] == 'L':
                    # # Letters: Lu=UPPERS, Ll=lowers, Lo=other (kanji,kana,etc)
                    _tlen = len(subx)
                    if _tlen > x_max_subword_len:
                        # # longer than max subword len; break into smaller pieces
                        tmp_l_list = []
                        _tdivs = int(_tlen / x_max_subword_len)
                        if _tlen % x_max_subword_len:
                            _tdivs += 1
                        _avgsz = int(_tlen / _tdivs)
                        if _tlen % _tdivs:
                            _avgsz += 1
                        _tcpos = 0
                        while _tcpos < _tlen - 1:
                            tmp_l_list.append(subx[_tcpos: _tcpos+_avgsz])
                            _tcpos += _avgsz
                    else:
                        tmp_l_list = [subx,]
                    for _ti in range(len(tmp_l_list)):
                        _t_sw = tmp_l_list[_ti]
                        # # assess all the pieces of sub-string and add
                        upper_count = 0
                        other_count = 0
                        _tweight = self.conf.weight_base
                        for tmp_letter in _t_sw:
                            tmp_cat = ucategory(tmp_letter)
                            if tmp_cat == 'Ll':
                                pass
                            elif tmp_cat == 'Lu':
                                upper_count += 1
                            else:
                                other_count += 1
                        if upper_count == len(_t_sw):
                            # # all caps. treat it close to a normal word
                            upper_count = 1
                        if other_count or upper_count:
                            _tweight += upper_count * self.conf.weight_uppers
                            _tweight += other_count * self.conf.weight_special
                            x_subwordlist_t.append('A')
                        else:
                            x_subwordlist_t.append('a')
                        _txtrachars = _tlen - self.conf.small_word_len
                        if _txtrachars > 0:
                            _tweight += _txtrachars * self.conf.weight_extra_char
                        if _ti > 0:
                            _tweight += self.conf.weight_subwords
                        x_subword_weights.append(_tweight)
                    x_subwordlist.extend(tmp_l_list)
                elif cat == 'Nd':
                    # # Numbers
                    if len(subx) > 3:
                        # # break it into chunks of 3 to be more readable
                        # # since we want to break where commas *would* be,
                        # #  we have to go right to left
                        tmp_n_list = []
                        _rpos = len(subx)
                        _lpos = _rpos - 3
                        while _rpos > 0:
                            tmp_n_list.insert(0, subx[_lpos:_rpos])
                            x_subwordlist_t.append('0')
                            x_subword_weights.append(self.conf.weight_numbers)
                            # # shift left on the number
                            _rpos -= 3
                            _lpos -= 3
                            if _lpos < 0:
                                _lpos = 0
                        x_subwordlist.extend(tmp_n_list)
                    else:
                        x_subwordlist.append(subx)
                        x_subwordlist_t.append('0')
                        x_subword_weights.append(self.conf.weight_numbers)
                elif cat[0] == 'P':
                    # # punctuation: Ps=start "[{(", Pe=end "}])",
                    # #              Pc=connector "_", Pd=dash "-", Po=other "@!$"
                    x_subwordlist.append(subx)
                    x_subwordlist_t.append('.')
                    x_subword_weights.append(self.conf.weight_punctuation)
                elif cat == 'Sm' or cat == 'Sc':
                    # # symbols: Sm=math "^~+", Sc=currency"$"
                    x_subwordlist.append(subx)
                    x_subwordlist_t.append('.')
                    x_subword_weights.append(self.conf.weight_punctuation)
                    # # TODO: Sk is *just* backtick? "`"
                elif cat == 'Zs':
                    # # space
                    if x_subwordlist:
                        _add_word_list()
                    x_subword_current_pos += 1
                    x_subword_start_pos = x_subword_current_pos
                    continue
                elif cat == 'Cc':
                    # # control, includes newlines, tabs and unprintable binary
                    if subx == self.newline:
                        ## add existing subword. make new word.
                        ## newline will show distinctly, ...
                        ## ...not as a continuation of the line before
                        ## newline as distinct word
                        if x_subwordlist:
                            ### process previous word seperately
                            _add_word_list()
                        x_subwordlist.append(subx)
                        x_subwordlist_t.append('\t')
                        x_subword_weights.append(self.conf.weight_special)
                        x_subword_start_pos = x_subword_current_pos
                        _add_word_list()
                        x_subword_current_pos += 1
                        x_subword_start_pos = x_subword_current_pos
                        continue
                    elif subx == '\t':
                        if x_subwordlist and x_subwordlist[-1] != '\t':
                            _add_word_list()
                        x_subwordlist.append(subx)
                        x_subwordlist_t.append('\t')
                        x_subword_weights.append(self.conf.weight_special)
                    else:
                        if x_subwordlist:
                            _add_word_list()
                        logger.warning('unrecognized characters (%d)' % x_subword_current_pos)
                        x_subwordlist.clear()
                        x_subword_current_pos += len(subx)
                        x_subword_start_pos = x_subword_current_pos

                x_subword_current_pos += len(subx)
            # # if full text is too big, get ready to read in more text
            x_re_init_pos += x_re_offset
        # # finished loops of all text; get the straggler at the end of the whole text...
        if x_subwordlist:
            _add_word_list()
        #self.word_struct = word_struct
        #self.subword_struct = subword_struct
        #self.word_structs = word_structs
        #self.subword_structs = subword_structs


def dbg(msg):
    logger.debug(msg)


def main():
    pass


if __name__ == '__main__':
    main()
