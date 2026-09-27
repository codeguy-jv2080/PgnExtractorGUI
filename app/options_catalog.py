"""A local reference catalogue for pgn-extract v26-06 options.

The GUI's structured controls cover common operations.  The catalogue is
returned to the browser so that the Advanced panel can explain every option
accepted by the bundled v26-06 command-line program.  Advanced arguments are
sent as literal argv tokens, never as a shell command string.
"""

from __future__ import annotations

from typing import Final

OPTION_CATALOG: Final[list[dict[str, str]]] = [
    # Inputs and criteria.
    {"flag": "-A argsfile", "group": "Input", "summary": "Read arguments from an argument file."},
    {"flag": "-f file_list", "group": "Input", "summary": "Read input PGN filenames from a file."},
    {"flag": "-t tagfile", "group": "Selection", "summary": "Match tags using a criteria file."},
    {"flag": "-T criterion", "group": "Selection", "summary": "Add a command-line tag criterion."},
    {"flag": "-H hash", "group": "Selection", "summary": "Match a Polyglot/Zobrist position hash."},
    {"flag": "-v variations", "group": "Selection", "summary": "Match textual move variations."},
    {"flag": "-x variations", "group": "Selection", "summary": "Match positions reached by variations."},
    {"flag": "-y file / --materialy material", "group": "Selection", "summary": "Match material balances."},
    {"flag": "-z file / --materialz material", "group": "Selection", "summary": "Match material balances and output related matches."},
    {"flag": "-b[elu] number", "group": "Selection", "summary": "Set exact, lower, or upper move-count bounds."},
    {"flag": "-p[elu] number", "group": "Selection", "summary": "Set exact, lower, or upper ply-count bounds."},
    {"flag": "--minmoves / --maxmoves", "group": "Selection", "summary": "Set move-count bounds."},
    {"flag": "--minply / --maxply", "group": "Selection", "summary": "Set ply-count bounds."},
    {"flag": "--firstgame / --gamelimit / --stopafter", "group": "Selection", "summary": "Limit the games examined or matched."},
    {"flag": "--selectonly / --skipmatching", "group": "Selection", "summary": "Select or omit matched game numbers."},
    {"flag": "--startply / --matchplylimit", "group": "Selection", "summary": "Control the depth at which positional matching occurs."},
    {"flag": "-M / --checkmate", "group": "Game endings", "summary": "Match checkmates only."},
    {"flag": "--stalemate / --insufficient", "group": "Game endings", "summary": "Match stalemates or insufficient-material endings."},
    {"flag": "--fifty / --seventyfive / --50 / --75", "group": "Game endings", "summary": "Match long no-capture/no-pawn-move sequences."},
    {"flag": "--repetition / --repetition5", "group": "Game endings", "summary": "Match threefold or fivefold repetitions."},
    {"flag": "--underpromotion / --odds", "group": "Selection", "summary": "Match underpromotions or games played at odds."},
    {"flag": "--higherratedwinner / --lowerratedwinner", "group": "Selection", "summary": "Match games based on winner rating."},
    {"flag": "--piececount / --quiescent", "group": "Position", "summary": "Match a piece count or position quiescence threshold."},
    {"flag": "--fenpattern / --fenpatterni", "group": "Position", "summary": "Match a FEN pattern for one or either side to move."},
    {"flag": "--wtm / --btm", "group": "Position", "summary": "Restrict position matches by side to move."},
    {"flag": "--nosetuptags / --onlysetuptags", "group": "Selection", "summary": "Filter games with FEN/SetUp tags."},
    {"flag": "--commented", "group": "Selection", "summary": "Match games containing at least one comment."},

    # Duplicate and matching behaviour.
    {"flag": "-c file / --checkfile", "group": "Duplicates", "summary": "Use a PGN/check-file list as a duplicate reference."},
    {"flag": "-d file / --duplicates", "group": "Duplicates", "summary": "Write duplicate games to a separate output file."},
    {"flag": "-D / --noduplicates", "group": "Duplicates", "summary": "Suppress duplicate games."},
    {"flag": "-U / --nounique", "group": "Duplicates", "summary": "Output only games that occur more than once."},
    {"flag": "-Z", "group": "Duplicates", "summary": "Use a disk-backed duplicate table for large data sets."},
    {"flag": "--fuzzydepth / --deletesamesetup", "group": "Duplicates", "summary": "Use positional duplicate matching or suppress repeated initial positions."},
    {"flag": "-P / --vanywhere", "group": "Variations", "summary": "Control textual variation permutation/placement matching."},
    {"flag": "--markmatches / --addlabeltag / --addmatchtag", "group": "Variations", "summary": "Mark position or material matches."},

    # Output destinations.
    {"flag": "-o file / --output", "group": "Output", "summary": "Write matched games to one new file (overwrites it)."},
    {"flag": "-a file / --append", "group": "Output", "summary": "Append matched games to a file."},
    {"flag": "-n file", "group": "Output", "summary": "Write non-matching games separately."},
    {"flag": "--suppressmatched", "group": "Output", "summary": "Suppress the matched side when using non-matching output."},
    {"flag": "-# number[,first]", "group": "Output", "summary": "Split output into numbered PGN files."},
    {"flag": "-E[level]", "group": "Output", "summary": "Split output into ECO-named PGN files."},
    {"flag": "-e[eco_file]", "group": "Output", "summary": "Classify games with an ECO file."},

    # Output formatting.
    {"flag": "-W[format]", "group": "Formatting", "summary": "Choose SAN, FEN, EPD, UCI, or algebraic output formats."},
    {"flag": "-w width / --linelength", "group": "Formatting", "summary": "Set the approximate output line length."},
    {"flag": "-7 / --seven", "group": "Formatting", "summary": "Output the seven-tag roster only."},
    {"flag": "-R roster / --xroster", "group": "Formatting", "summary": "Order and optionally limit output tags."},
    {"flag": "--notags / --detag", "group": "Formatting", "summary": "Omit all tags or a named tag."},
    {"flag": "-C / --nocomments", "group": "Formatting", "summary": "Remove comments."},
    {"flag": "-N / --nonags", "group": "Formatting", "summary": "Remove NAGs."},
    {"flag": "-V / --novars", "group": "Formatting", "summary": "Remove variations."},
    {"flag": "--nomovenumbers / --noresults / --nochecks", "group": "Formatting", "summary": "Omit move numbers, results, or check/mate marks."},
    {"flag": "--plylimit / --dropply / --dropbefore", "group": "Formatting", "summary": "Limit or remove opening output plies."},
    {"flag": "--splitvariants", "group": "Formatting", "summary": "Emit variations as separate games."},
    {"flag": "--json", "group": "Formatting", "summary": "Write games as JSON."},
    {"flag": "-F[text] / --fencomments / --fencommentformat", "group": "Formatting", "summary": "Include FEN comments."},
    {"flag": "--hashcomments / --addhashcode", "group": "Formatting", "summary": "Include Polyglot hash comments or tags."},
    {"flag": "--evaluation / --plycount / --totalplycount", "group": "Formatting", "summary": "Add derived annotations or tags."},
    {"flag": "--addelotags / --addfideidtags / --addfencastling", "group": "Formatting", "summary": "Add or repair selected tags."},
    {"flag": "--fixresulttags / --fixtagstrings / --lichesscommentfix", "group": "Formatting", "summary": "Repair common PGN issues."},
    {"flag": "--commentlines / --linenumbers", "group": "Formatting", "summary": "Adjust comment layout or include input line numbers."},
    {"flag": "--nofauxep", "group": "Formatting", "summary": "Omit impossible en-passant data in FEN."},

    # Parsing and diagnostics.
    {"flag": "-r", "group": "Diagnostics", "summary": "Report errors without extracting games."},
    {"flag": "-l file / -L file", "group": "Diagnostics", "summary": "Write or append diagnostics to a log file."},
    {"flag": "-s / --quiet / --summary", "group": "Diagnostics", "summary": "Reduce status output or show a final match count."},
    {"flag": "--keepbroken / --nobadresults", "group": "Parsing", "summary": "Retain broken games or reject inconsistent results."},
    {"flag": "--allownullmoves / --nestedcomments", "group": "Parsing", "summary": "Accept null moves or nested comments."},
    {"flag": "-S / --tagsubstr", "group": "Matching", "summary": "Use Soundex or substring tag matching."},
    {"flag": "-h / --help / --version", "group": "Information", "summary": "Display program help or version information."},
]


def catalog_by_group() -> dict[str, list[dict[str, str]]]:
    """Return a display-friendly catalogue grouped by function."""

    groups: dict[str, list[dict[str, str]]] = {}
    for option in OPTION_CATALOG:
        groups.setdefault(option["group"], []).append(option)
    return groups
