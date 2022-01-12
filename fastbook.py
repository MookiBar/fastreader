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
                       ' weight_subwords small_word_len weight_extra_char speed_adjust')
#class DefaultSettings():
DefaultConf = ConfTuple(
    max_subword_len=7,
    weight_base=8,  # #float/double: for normal words, per char
    weight_special=5,  # #float/double: for abnormal words, per char
    weight_uppers=6,  # #float/double: for each capital letter
    weight_numbers=10,
    weight_subwords=2,
    small_word_len=4,  # #uint: small words get same fast pace
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
        ##########################################################
        ############################## START SUB-DEF _add_to_words
        def _add_to_words():
            nonlocal self
            #nonlocal word_struct
            #nonlocal word_structs
            #nonlocal subword_struct
            #nonlocal subword_structs
            nonlocal flags
            nonlocal subwordlist
            nonlocal subword_start_pos
            nonlocal subword_current_pos
            ### XXX DEBUG TODO
            logger.debug('processing word: %s (pos: %d)' %
                         (repr(subwordlist), subword_start_pos)
                         )
            newflags = flags
            # # to immediately set flags for current element, assign to `flags`
            # # otherwise, `newflags` will set flags for next element
            if len(subwordlist) > self.max_byte_num:
                logger.warning(
                    'subword list must be truncated (len %d after pos %d' % \
                    (len(subwordlist), subword_start_pos)
                )
                subwordlist = subwordlist[:self.max_byte_num]
            ## ^ can only store one byte for subword count
            #tmpcharpos = subwordlist.pop(0) # ??
            subword_count = len(subwordlist)
            tmpwordlen = len(''.join(subwordlist))
            tmp_wordindex = len(self.word_structs) / self.word_struct.size
            ### Word
            ### char_pos, word_len, subword_index, subword_count
            self.word_structs.extend(
                self.word_struct.pack(
                    subword_start_pos,
                    tmpwordlen,
                    self.get_subword_count(),
                    subword_count
                )
            )
            wordlen = 0
            tmpcharpos = 0
            for xi in range(subword_count):
                tmpsubword = subwordlist[xi]
                tmpsubwordlen = len(tmpsubword)
                if tmpsubwordlen > self.max_byte_num:
                    logger.warning('subword too large, char pos: %d' % subword_current_pos)
                    tmpsubword = tmpsubword[:self.max_byte_num]
                    tmpsubwordlen = len(tmpsubword)
                tmpweight = self._get_weight(tmpsubword)
                if subword_count > 1:
                    subword_weight_o = tmpweight * self.conf.weight_subwords / self.conf.weight_base
                    #subword_weight_o = xi * subword_count * self.conf.weight_subwords
                    #subword_weight_o /= (1 + self.conf.max_subword_len - tmpsubwordlen)
                    #if subword_weight_o > 20:
                    #    subword_weight_o = 20
                    #elif subword_weight_o < 0:
                    #    subword_weight_o = 0
                    tmpweight += int(subword_weight_o)
                    # XXX
                    # # check for quotes, bold, italics (gutenberg)
                    # # iff at beginning or end of word
                    ######################
                    if tmpsubword == '"':
                        if flags & FormatFlags.QUOTES:
                            # # end-quotes must come after letters/nums
                            # # ...and should not have letters/nums after it
                            if xi == tmpsubwordlen - 1:
                                flags &= ~ FormatFlags.QUOTES
                            else:
                                xgood = False
                                for xj in subwordlist[:xi]:
                                    tmp_uc = ucategory(xj[0])
                                    if tmp_uc == 'Lu' or tmp_uc == 'Ll' or tmp_uc == 'Nd':
                                        xgood = True
                                        break
                                for xj in subwordlist[xi + 1:]:
                                    tmp_uc = ucategory(xj[0])
                                    if tmp_uc == 'Lu' or tmp_uc == 'Ll' or tmp_uc == 'Nd':
                                        xgood = False
                                        break
                                if xgood:
                                    newflags &= ~ FormatFlags.QUOTES
                                    flags &= ~ FormatFlags.QUOTES
                        else:
                            # # quotes not set, check if we should set it
                            if xi == 0:
                                # # beginning of word = good to set
                                newflags |= FormatFlags.QUOTES
                            else:
                                # # should have letters/nums after, none before
                                xgood = False
                                for xj in subwordlist[xi + 1:]:
                                    tmp_uc = ucategory(xj[0])
                                    if tmp_uc == 'Lu' or tmp_uc == 'Ll' or tmp_uc == 'Nd':
                                        xgood = True
                                        break
                                for xj in subwordlist[:xi]:
                                    tmp_uc = ucategory(xj[0])
                                    if tmp_uc == 'Lu' or tmp_uc == 'Ll' or tmp_uc == 'Nd':
                                        xgood = False
                                        break
                                if xgood:
                                    newflags &= ~ FormatFlags.QUOTES
                    #########################
                    elif tmpsubword == '*':
                        # # toggle BOLD?
                        if flags & FormatFlags.BOLD:
                            # # bold already set, check if we should unset it
                            if xi == tmpsubwordlen - 1:
                                flags &= ~ FormatFlags.BOLD
                                newflags &= ~ FormatFlags.BOLD
                                tmpweight = -1
                            else:
                                xgood = False
                                for xj in subwordlist[:xi]:
                                    tmp_uc = ucategory(xj[0])
                                    if tmp_uc == 'Lu' or tmp_uc == 'Ll' or tmp_uc == 'Nd':
                                        xgood = True
                                        break
                                for xj in subwordlist[xi + 1:]:
                                    tmp_uc = ucategory(xj[0])
                                    if tmp_uc == 'Lu' or tmp_uc == 'Ll' or tmp_uc == 'Nd':
                                        xgood = False
                                        break
                                if xgood:
                                    flags &= ~ FormatFlags.BOLD
                                    newflags &= ~ FormatFlags.BOLD
                                    tmpweight = -1
                        else:
                            # # bold not set, check if we should set it
                            if xi == 0:
                                # # beginning of word = good to set
                                flags |= FormatFlags.BOLD
                                newflags |= FormatFlags.BOLD
                                tmpweight = -1
                            else:
                                # # should have letters/nums after, none before
                                xgood = False
                                for xj in subwordlist[xi + 1:]:
                                    tmp_uc = ucategory(xj[0])
                                    if tmp_uc == 'Lu' or tmp_uc == 'Ll' or tmp_uc == 'Nd':
                                        xgood = True
                                        break
                                for xj in subwordlist[:xi]:
                                    tmp_uc = ucategory(xj[0])
                                    if tmp_uc == 'Lu' or tmp_uc == 'Ll' or tmp_uc == 'Nd':
                                        xgood = False
                                        break
                                if xgood:
                                    flags |= FormatFlags.BOLD
                                    newflags |= FormatFlags.BOLD
                                    tmpweight = -1
                ###############################
                    elif tmpsubword == '_':
                        if flags & FormatFlags.ITALICS:
                            # # bold already set, check if we should unset it
                            if xi == tmpsubwordlen - 1:
                                flags &= ~ FormatFlags.ITALICS
                                newflags &= ~ FormatFlags.ITALICS
                                tmpweight = -1
                            else:
                                xgood = False
                                for xj in subwordlist[:xi]:
                                    tmp_uc = ucategory(xj[0])
                                    if tmp_uc == 'Lu' or tmp_uc == 'Ll' or tmp_uc == 'Nd':
                                        xgood = True
                                        break
                                for xj in subwordlist[xi + 1:]:
                                    tmp_uc = ucategory(xj[0])
                                    if tmp_uc == 'Lu' or tmp_uc == 'Ll' or tmp_uc == 'Nd':
                                        xgood = False
                                        break
                                if xgood:
                                    flags &= ~ FormatFlags.ITALICS
                                    newflags &= ~ FormatFlags.ITALICS
                                    tmpweight = -1
                        else:
                            # # bold not set, check if we should set it
                            if xi == 0:
                                # # beginning of word = good to set
                                flags |= FormatFlags.ITALICS
                                newflags |= FormatFlags.ITALICS
                                tmpweight = -1
                            else:
                                # # should have letters/nums after, none before
                                xgood = False
                                for xj in subwordlist[xi + 1:]:
                                    tmp_uc = ucategory(xj[0])
                                    if tmp_uc == 'Lu' or tmp_uc == 'Ll' or tmp_uc == 'Nd':
                                        xgood = True
                                        break
                                for xj in subwordlist[:xi]:
                                    tmp_uc = ucategory(xj[0])
                                    if tmp_uc == 'Lu' or tmp_uc == 'Ll' or tmp_uc == 'Nd':
                                        xgood = False
                                        break
                                if xgood:
                                    flags |= FormatFlags.ITALICS
                                    newflags |= FormatFlags.ITALICS
                                    tmpweight = -1

                ###
                ### char_pos, subword_len, word_index, subword_count, flags, weight
                if tmpweight == -1:
                    tmpflags = FormatFlags.IGNORE
                    tmpweight = 0
                elif tmpsubword[0] == '\n' or tmpsubword == '\r':
                    if tmpsubword == self.newline:
                        tmpflags = FormatFlags.SPECIAL
                        # # if we wanted to reset all flags at a newline, we'd do it here
                        #flags = 0
                    else:
                        tmpflags = FormatFlags.IGNORE
                elif tmpsubword == '\t':
                    tmpflags = FormatFlags.SPECIAL
                else:
                    tmpflags = flags
                #logger.debug(
                #    'pack subword: '
                #    'subword_len:%d '
                #    'weight:%d flags:%d' % (
                #        tmpsubwordlen,
                #        tmpweight,
                #        tmpflags,
                #    ))
                if tmpsubwordlen > 255:
                    logger.error('subword too long: %d: %d' % (subword_current_pos, tmpsubwordlen))
                    tmpsubwordlen = 255
                tmpweight = int(tmpweight)
                if tmpweight > 255:
                    logger.error('weight too big: %d: %d' % (subword_current_pos, tmpweight))
                    tmpweight = 255
                if tmpflags > 255:
                    logger.error('flags be crazy: %d: %d' % (subword_current_pos, tmpflags))
                tmpsubarr = self.subword_struct.pack(
                    tmpsubwordlen,
                    int(tmpweight),
                    tmpflags,
                )  ## asdf asdf asdf
                self.subword_structs.extend(
                    tmpsubarr
                )
                tmpcharpos += len(tmpsubword)
                flags = newflags

        ############################## END SUB-DEF _add_to_words
        ###########################################
        self._detect_encoding()
        ## TODO: something with encoding...?
        self._get_newline()
        subword_start_pos = 0
        subword_current_pos = 0
        re_init_pos = 0
        re_offset = self.max_chunk_size
        subwordlist = []
        ## read ~100k chars at a time. makes memload smaller during parsing
        while re_init_pos < len(self.text):
            subtxt = self.text[re_init_pos:re_init_pos + re_offset]
            logger.debug('len subtxt: %d' % len(subtxt))
            #splitoutlist = re.split('(\W|\w{1,%d})' % self.conf.max_subword_len, subtxt)
            splitoutlist = re.split('([^a-zA-Z0-9]|[0-9]{1,3}|[a-zA-Z]{1,%d})' % self.conf.max_subword_len, subtxt)
            #logger.debug('len splitoutlist: %d' % len(splitoutlist))
            for tmpindex in range(len(splitoutlist)):
                i = splitoutlist[tmpindex]
                if not i:
                    continue
                #logger.debug('i: %s' % repr(i))
                if not i:
                    continue
                elif i[0] == '\n' or i == '\r':
                    if i == self.newline:
                        ## add existing subword. make new word.
                        ## newline will show distinctly, ...
                        ## ...not as a continuation of the line before
                            ## newline as distinct word
                        if subwordlist:
                            ### process previous word seperately
                            _add_to_words()
                        subwordlist = [i]
                        subword_start_pos = subword_current_pos
                        _add_to_words()
                        subword_current_pos += 1
                        subword_start_pos = subword_current_pos
                        subwordlist = []
                        continue
                    else:
                        ## ignore completely
                        if subwordlist:
                            _add_to_words()
                        subwordlist = []
                        subword_current_pos += 1
                        subword_start_pos = subword_current_pos
                        continue
                elif i == '\t':
                    if subwordlist and subwordlist[-1] == '\t':
                        ## tabs attach together
                        subwordlist.append(i)
                    elif subwordlist:
                        ## process wordlist. tab attaches to next word...
                        _add_to_words()
                        subword_start_pos = subword_current_pos
                        subword_current_pos += 1
                        continue
                    else:
                        subwordlist.append(i)
                elif i == ' ':
                    logger.debug('space at pos: %d' % subword_current_pos)
                    if subwordlist:
                        # # process wordlist. skip space.
                        _add_to_words()
                    subword_current_pos += 1
                    subword_start_pos = subword_current_pos
                    subwordlist = []
                    continue
                elif tmpindex + 1 == len(splitoutlist):
                    subwordlist.append(i)
                    _add_to_words()
                else:
                    subwordlist.append(i)
                subword_current_pos += len(i)
            # # if full text is too big, get ready to read in more text
            re_init_pos += re_offset
        # # finished loops of all text; get the straggler at the end of the whole text...
        if subwordlist:
            _add_to_words()
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
