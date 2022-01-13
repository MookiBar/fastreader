#!/usr/bin/env python3

import fastbook
import argparse
import sys
import tty
import termios
import threading
import traceback
from time import sleep
import logging
import logging.handlers

logger = logging.getLogger('fastreader')
logger.setLevel(logging.ERROR)

ERR_TO_CONSOLE = False

if ERR_TO_CONSOLE:
    for handler in logger.handlers:
        handler.setLevel(logging.ERROR)
else:
    try:
        logger.handlers.clear()
    except AttributeError:
        for handler in logger.handlers:
            logger.removeHandler(handler)

orig_settings = termios.tcgetattr(sys.stdin)

FAIL = None

DEBUG_FILE = '/tmp/fastreader.debug'

PARSER = argparse.ArgumentParser(description='This program takes text'
                                             ' from stdin or file and starts a console'
                                             ' version of fastreader.')
PARSER.add_argument('-f', '--filename', metavar='FILE', type=str, help='file to parse')
PARSER.add_argument('-w', '--word', metavar='WORDNUM', type=int,
                    help='optional: index of word to start at')
PARSER.add_argument('-s', '--speed', metavar='SPEEDNUM', type=int,
                    help='optional: speed to start at')
PARSER.add_argument('-d', '--debug', action='store_true', help='turn on debug output to file: %s' % DEBUG_FILE)
PARSER.add_argument('--demo', action='store_true', help='run a demo recommended for beginners')
# # TODO: find a way to read from stdin for text and then stdin for keystrokes
# parser.add_argument('-s', '--stdin', action='store_true', help='parse text from stdin')

FONT = {
    'grey': '\x1b[30m',
    'red': '\x1b[31m',
    'green': '\x1b[32m',
    'yellow': '\x1b[33m',
    'blue': '\x1b[34m',
    'purple': '\x1b[35m',
    'teal': '\x1b[36m',
    'white': '\x1b[37m',
    'bold': '\x1b[1m',
    'italic': '\x1b[3m',
    'clear': '\x1b(B\x1b[m',
    'newline': '- - ',
    'tab': '_ ',
}

SIGNS = {
    'pause': '||',
    'play': '.>.',
    'left': '<-',
    'right': '->',
    'faster': '>+',
    'slower': '>-',
    'quit': '*STOP*',
    'unknown': '(X)',
}

demo_txt = """
...Okay.
Relax.
Relax...
...Let your eyes rest right here on the screen.
Focus here
in the center and let your eyes stay.
Let your eyes relax, let your mind relax, let all of your senses relax as you let yourself soak in these words.
Let the words wash over you. No need to think about it. Just let it happen....
Stay here in the center. Stay right here and let your eyes soak in these words.
As you become more and more relaxed, you will absorb more and more words.
The more words you see, the more you will retain the information without even thinking about it.
As you practice this new reading experience more and more, you will soon become an _expert_.
You will tell all your friends, "I can read so fast! I can read faster than you can possibly imagine!"
And you can do it without even trying. That is it. *Now you are ready.*
Find a book.....and relax... Relax! Find a book at let the moment take you.
Do it!
"""

def log_to_debug_file():
    filehandler = logging.handlers.RotatingFileHandler(
            DEBUG_FILE, maxBytes=10485760, backupCount=3
            )
    #filehandler.setFormatter('XXX')
    filehandler.setLevel(logging.DEBUG)
    filehandler.set_name('filelogger')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(filehandler)



def _die(ret_code=0):
    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, orig_settings)
    sys.exit(ret_code)


def uncaught_exception_handler(exc_type, exc, tb):
    global FAIL
    FAIL = True
    logger.exception(exc)
    logging.critical('UNCAUGHT EXCEPTION: {}: {}'.format(exc_type, exc))
    logging.critical('traceback: %s' % '|'.join(traceback.format_tb(tb)))

    _die(253)


sys.excepthook = uncaught_exception_handler

class Reader():
    def __init__(self, text, speed=10, max_speed=90, auto_speed_up=False):
        logger.debug('__init__()')
        self.auto_speed_up = auto_speed_up
        self.max_speed = max_speed
        self.pause = True
        self.stopping = False
        self.speed = speed
        self.current_word_num = 0
        self.current_subword_num = 0
        self.lock = threading.Lock()
        self._extra_input = SIGNS['pause']
        self.input_buffer = []
        self.book = fastbook.Book(text)
        self.center_len = self.book.conf.max_subword_len
        self.side_len = self.book.conf.max_subword_len * 2
        self.max_width = 40
        self.font_muted = FONT['grey']
        self.font_normal = FONT['white']
        self.font_quote = FONT['teal']
        self.font_italic = FONT['italic']
        self.font_bold = FONT['bold']
        self.font_newline = '_'
        # # just so my ide doesn't get annoyed...but change_to_word_num() does this anyways...
        self.current_word_pack = self.book.get_word_pack_at_index(0)
        self.change_to_word_num(0)
        self.word_popper_thread = threading.Thread(target=self.word_popper)
        self.key_checker_thread = threading.Thread(target=self.key_checker)

    def start(self):
        #log_to_debug_file()
        logger.debug('start()')
        self.display_banner()
        self._setup_tty()
        sys.stdout.write('%s press spacebar %s\r' % (FONT['italic'] + FONT['bold'], FONT['clear']))
        sys.stdout.flush()
        #self.display_word()
        self.word_popper_thread.start()
        self.key_checker_thread.start()
        self.key_checker_thread.join()
        self.word_popper_thread.join()

    def _setup_tty(self):
        # # set terminal to buffer one char at a time
        tty.setcbreak(sys.stdin)

    def change_to_word_num(self, index):
        logger.debug('change_to_word_num(%d)' % index)
        self.current_subword_num = 0
        self.current_word_num = index
        tmp_word_pack = self.book.get_word_pack_at_index(index)
        subwords, flags, weights = tmp_word_pack
        for i in range(len(flags)):
            if flags[i] & fastbook.FormatFlags.SPECIAL:
                if subwords[i] == self.book.newline:
                    subwords[i] = FONT['newline']
                elif subwords[i] == '\t':
                    subwords[i] = FONT['tab']
        self.current_word_pack = (subwords, flags, weights)

    def display_word(self):
        logger.debug('display_word()')
        logger.debug('current_word_pack: %s' % repr(self.current_word_pack))
        logger.debug('word/sub: %d, %d' % (self.current_word_num, self.current_subword_num))
        subwords, flags, weights = self.current_word_pack
        #for i in range(len(flags)):
        #    if flags[i] & fastbook.FormatFlags.SPECIAL:
        #        logging.debug('SPECIAL FLAG AT %d,%d' % (self.current_word_num,i))
        #        subwords = list(subwords)
        #        if subwords[i] == self.book.newline:
        #            subwords[i] = FONT['newline']
        #        elif subwords[i] == '\t':
        #            subwords[i] == FONT['tab']
        #        else:
        #            logging.error('unknown subword at %d,%d' %
        #                          (self.current_word_num ,self.current_subword_num))
        center = subwords[self.current_subword_num]
        font_flags = ''
        curr_flags = flags[self.current_subword_num]
        if curr_flags & fastbook.FormatFlags.ITALICS:
            font_flags = font_flags + self.font_italic
        if curr_flags & fastbook.FormatFlags.BOLD:
            font_flags = font_flags + self.font_italic
        if curr_flags & fastbook.FormatFlags.QUOTES:
            font_flags = font_flags + self.font_quote
        else:
            font_flags = font_flags + self.font_normal
        if self.current_subword_num == 0:
            # is first subword
            left = ''
        else:
            left = ''.join(subwords[:self.current_subword_num])
        if self.current_subword_num == (len(subwords) - 1):
            # is last subword
            right = ''
        else:
            right = ''.join(subwords[self.current_subword_num + 1:])
        # # make left and right match length for centering
        if not left and not right:
            pass
        elif len(left) > len(right) and len(left) > self.book.conf.max_subword_len:
            right = '%s%s' % (right, ' ' * (len(left) - len(right)))
        elif right:
            left = '%s%s' % (' ' * len(right), left)
            #left = '%s%s' % (' ' * (len(right) - len(left)), left)
        # # every two chars causes one shift left; offset one against every two shifts
        left = '%s%s' % (' ' * int(len(center)/4), left)
        # # this is the line to be centered; all other adjustments/offsets must be complete
        xline = '{left}\x01{center}\x02{right}'.format(
            left=left, center=center, right=right,
        )
        if len(xline) > self.max_width:
            tmp_diff = int((len(xline) - self.max_width) / 2)
            xline = xline[tmp_diff+1:-tmp_diff]
        xline = xline.center(self.max_width, ' ')
        xline = xline.replace('\x01', font_flags)
        xline = xline.replace('\x02', FONT['clear'] + self.font_muted)
        xline = '{muted}{xline}{clear}'.format(
            muted = self.font_muted,
            xline=xline,
            clear=FONT['clear'],
        )
        if self._extra_input or self.input_buffer:
            if self.input_buffer:
                tmpbuffer = ' [%s]' % ''.join(self.input_buffer)
            else:
                tmpbuffer = ''
            tmpline = '{line}{clear}{font}{input}{buffer}{clear}    \r'.format(
                line=xline, clear=FONT['clear'], font=FONT['purple'],
                input=self._extra_input, buffer=tmpbuffer
            )
            self._extra_input = ''
        else:
            tmpline = '%s          \r' % xline
        sys.stdout.write(tmpline)
        sys.stdout.flush()

    def _exit_text(self):
        args = PARSER.parse_args()
        print("""
                       {red}...stopping at word: {word} ; speed {speed}
               {yellow}To resume, run: 
                       {prog} -f {file} -w {word} -s {speed}{clear}""".format(
            prog=sys.argv[0], file=args.filename,
            word=self.current_word_num, speed=self.speed,
            red=FONT['red'], yellow=FONT['yellow'], clear=FONT['clear'],
        )
        )

    def word_popper(self):
        logger.debug('word_popper()')
        while True:
            if FAIL:
                return
            if self.current_word_num >= self.book.get_word_count():
                self.current_word_num = self.book.get_word_count() - 1
            subwords, flags, weights = self.current_word_pack
            if self.stopping:
                self._exit_text()
                return
            if self.pause:
                sleep(0.1)
                continue
            else:
                sleep_num = weights[self.current_subword_num] / self.speed
                sleep(sleep_num)
            if self.stopping:
                self._exit_text()
                return
            if self.pause:
                sleep(0.1)
                continue
            elif self.current_word_num == self.book.get_word_count() - 1:
                with self.lock:
                    self.pause = True
                    self._extra_input = '%s (END) %s' % (SIGNS['pause'],self._extra_input)
                    self.display_word()
            else:
                with self.lock:
                    self.current_subword_num += 1
                    if self.current_subword_num >= len(subwords):
                        self.change_to_word_num(self.current_word_num + 1)
                    if self.auto_speed_up and self.speed < self.max_speed:
                        if self.current_word_num % 2:
                            self.speed += 1
                    self.display_word()

    def display_banner(self):
        sys.stdout.write("""{yellow}

command keys:
            <spacebar>) toggle play/pause
            j) speed down
            k) speed up
            q) quit/exit the program
while paused:
            h) previous-word                        gg) skip to beginning text
            l) next-word                            GG) skip to end of text
            /) search forward (case-sensitive)      ^) skip to start of line
            ?) search backward (case-sensitive)     $) skip to end of line
            {clear}
        \n""".format(yellow=FONT['yellow'],clear=FONT['clear']))
        sys.stdout.flush()

    def search_for_buffer(self):
        # # search forward from current index for the text held in buffer
        xinput = self.input_buffer.copy()
        self.input_buffer.clear()
        x = xinput.pop(0)
        if not xinput:
            return
        elif x != '/':
            self._extra_input += '   (ERR)'
            logger.error('unknown start of search buffer: %s' % ''.join(self.input_buffer))
            self.display_word()
            return
        else:
            curr_pos = self.book.get_char_pos_at_word_index(self.current_word_num)
            new_pos = self.book.text.find(''.join(xinput), curr_pos)
            if new_pos == -1:
                with self.lock:
                    self._extra_input = SIGNS['unknown']
                    self.display_word()
            else:
                self.change_to_word_num(self.book.get_word_index_at_char_pos(new_pos))
                with self.lock:
                    self._extra_input = '%s w:%d' % (SIGNS['right'], self.current_word_num)
                    self.display_word()

    def reverse_search_for_buffer(self):
        # # search back from current index for text held in buffer
        xinput = self.input_buffer.copy()
        self.input_buffer.clear()
        x = xinput.pop(0)
        if not xinput:
            return
        elif x != '?':
            logger.error('unknown start of reverse search buffer: %s' % ''.join(self.input_buffer))
            self.display_word()
            return
        else:
            curr_pos = self.book.get_char_pos_at_word_index(self.current_word_num)
            new_pos = self.book.text.rfind(''.join(xinput), 0, curr_pos)
            if new_pos == -1:
                with self.lock:
                    self._extra_input = SIGNS['unknown']
                    self.display_word()
            else:
                self.change_to_word_num(self.book.get_word_index_at_char_pos(new_pos))
                with self.lock:
                    self._extra_input = '%s w:%d' % (SIGNS['right'], self.current_word_num)
                    self.display_word()

    def goto_line_begin(self):
        curr_pos = self.book.get_char_pos_at_word_index(self.current_word_num)
        new_pos = self.book.text.rfind(self.book.newline, 0, curr_pos)
        if new_pos == -1:
            new_pos = 0
        else:
            new_pos += 1
        self.change_to_word_num(self.book.get_word_index_at_char_pos(new_pos))
        self._extra_input = '%s w:%d' % (SIGNS['left'], self.current_word_num)
        self.display_word()

    def goto_line_end(self):
        curr_pos = self.book.get_char_pos_at_word_index(self.current_word_num)
        new_pos = self.book.text.find(self.book.newline, curr_pos)
        if new_pos == -1:
            new_pos = len(self.book.text) - 1
        else:
            new_pos -= 1
        self.change_to_word_num(self.book.get_word_index_at_char_pos(new_pos))
        self._extra_input = '%s w:%d' % (SIGNS['right'], self.current_word_num)
        self.display_word()

    def key_checker(self):
        while True:
            if FAIL:
                return
            if not self.word_popper_thread.is_alive():
                return
            x = sys.stdin.read(1)[0]
            logger.debug('key_checker: %d' % ord(x))
            if ord(x) == 27:
                with self.lock:
                    self._extra_input = '%s (esc)' % SIGNS['unknown']
                    self.input_buffer.clear()
                    self.display_word()
                continue
            elif self.pause and self.input_buffer and self.input_buffer[0] == '/':
                if x == '\n' or x == '\r':
                    self.search_for_buffer()
                else:
                    with self.lock:
                        self.input_buffer.append(x)
                        self.display_word()
            elif self.pause and self.input_buffer and self.input_buffer[0] == '?':
                if x == '\n' or x == '\r':
                    self.reverse_search_for_buffer()
                else:
                    with self.lock:
                        self.input_buffer.append(x)
                        self.display_word()
            elif self.pause and not self.input_buffer and x == '/':
                with self.lock:
                    self.input_buffer.append(x)
                    self.display_word()
            elif self.pause and not self.input_buffer and x == '?':
                with self.lock:
                    self.input_buffer.append(x)
                    self.display_word()
            elif x == 'q':
                # quit
                with self.lock:
                    self.input_buffer.clear()
                    self.stopping = True
                    self._extra_input = SIGNS['quit']
                    self.display_word()
                return
            elif self.pause and x == 'g':
                if len(self.input_buffer) == 1 and self.input_buffer[0] == 'g':
                    with self.lock:
                        self.input_buffer.clear()
                        self.change_to_word_num(0)
                        self._extra_input = '%s (START)' % SIGNS['left']
                        self.display_word()
                elif not self.input_buffer:
                    self.input_buffer.append(x)
                else:
                    self.input_buffer.clear()
                    self._extra_input += SIGNS['unknown']
            elif self.pause and x == 'G':
                if len(self.input_buffer) == 1 and self.input_buffer[0] == 'G':
                    with self.lock:
                        self.input_buffer.clear()
                        self.change_to_word_num(self.book.get_word_count() - 1)
                        self._extra_input = '%s (END)' % SIGNS['right']
                        self.display_word()
                elif not self.input_buffer:
                    self.input_buffer.append(x)
                else:
                    self.input_buffer.clear()
                    self._extra_input += SIGNS['unknown']
            elif x == ' ':
                # toggle pause
                with self.lock:
                    if self.pause:
                        self.pause = False
                        self._extra_input = SIGNS['play']
                        self.display_word()
                    else:
                        self.pause = True
                        self._extra_input = '%s w:%d' % (SIGNS['pause'], self.current_word_num)
                        self.display_word()
            elif x == 'k':
                #up
                if self.speed < self.max_speed:
                    with self.lock:
                        self.speed += 1
                        self._extra_input = '%s%d' % (SIGNS['faster'], self.speed)
                        self.display_word()
                else:
                    with self.lock:
                        self._extra_input = '%s%d(MAX)' % (SIGNS['faster'], self.speed)
                        self.display_word()
            elif x == 'j':
                # down
                if self.speed <= 1:
                    with self.lock:
                        self._extra_input = '%s%d(X)' % (SIGNS['slower'], self.speed)
                        self.display_word()
                else:
                    with self.lock:
                        self.speed -= 1
                        self._extra_input = '%s%d' % (SIGNS['slower'], self.speed)
                        self.display_word()
            elif x == 'h':
                # left
                if self.pause and self.current_word_num > 0:
                    self.change_to_word_num(self.current_word_num - 1)
                    self._extra_input = '%s w:%d' % (SIGNS['left'], self.current_word_num)
                    self.display_word()
                else:
                    with self.lock:
                        self._extra_input = SIGNS['unknown']
                        self.display_word()
            elif x == 'l':
                # right
                if self.pause and self.current_word_num < (self.book.get_word_count() - 1):
                    self.change_to_word_num(self.current_word_num + 1)
                    self._extra_input = '%s w:%d' % (SIGNS['right'], self.current_word_num)
                    self.display_word()
                else:
                    with self.lock:
                        self._extra_input = SIGNS['unknown']
                        self.display_word()
            elif x == 'g':
                if self.pause:
                    pass #start of doc, double
                else:
                    with self.lock:
                        self._extra_input = SIGNS['unknown']
                        self.display_word()
            elif x == 'G':
                if self.pause:
                    pass #end of doc, double?
                else:
                    with self.lock:
                        self._extra_input = SIGNS['unknown']
                        self.display_word()
            elif x == '^':
                if self.pause:
                    self.goto_line_begin()
                else:
                    with self.lock:
                        self._extra_input = SIGNS['unknown']
                        self.display_word()
            elif x == '$':
                if self.pause:
                    self.goto_line_end()
                else:
                    with self.lock:
                        self._extra_input = SIGNS['unknown']
                        self.display_word()
            else:
                with self.lock:
                    self._extra_input = SIGNS['unknown']
                    self.display_word()


def main():
    args = PARSER.parse_args()

    if args.debug:
        log_to_debug_file()

    if args.demo:
        orig_txt = demo_txt
        speed = 5
        speedup = True
    else:
        speedup = False
        if not args.filename:
            PARSER.error('filename required.')
        try:
            with open(args.filename, 'r') as filey:
                orig_txt = filey.read()
        except Exception as e:
            PARSER.error(repr(e))
        if args.speed is None:
            speed = 20
        else:
            if args.speed <= 0 or args.speed >= 200:
                PARSER.error('speed must be a number between 1 and 200')
            else:
                speed = args.speed
    if not sys.stdin.isatty():
        PARSER.error('must be run in a tty without pipes.')
        sys.exit(5)

    sys.stdout.write('\n%s%sloading...%s\r' % (FONT['grey'], FONT['italic'], FONT['clear']))
    reader = Reader(text=orig_txt, speed=speed, max_speed=70, auto_speed_up=speedup)
    if not reader.book.get_word_count():
        PARSER.error('text has no valid words')
    if args.word:
        if args.word < 0:
            PARSER.error('number of starting word must be 0 or greater')
        elif args.word >= reader.book.get_word_count():
            PARSER.error('maximum word number for this book is {max}'.format(
                max=reader.book.get_word_count() - 1)
            )
        else:
            reader.change_to_word_num(args.word)
    reader.start()
    _die()


if __name__ == '__main__':
    main()
