#!/usr/bin/env python

from __future__ import print_function
import argparse
import csv
import pandas as pd
import numpy as np
from os import path
import sys
import re
from tempfile import TemporaryDirectory

__author__ = "Gavin Douglas"
__license__ = "GPL"
__version__ = "0.3"

parser = argparse.ArgumentParser(

description="Fix STAMP-formatted OTU table so all level labels in the file form a strict "
            "hierarchy. A strict hiearchy means that a child level can only "
            "have a single parent (e.g. the level \"unknown\" cannot follow "
            "two different Phylum names. The exception is \"Unclassified\", "
            "which is interpreted correctly by STAMP. Identical child labels "
            "with multiple parents will be distinguished by adding \"_dupN\" "
            "to the end of the label. Where N starts at 0 and is incremented "
            "for each new conflicting label (including the first one). "
            "This script will also accept the option \"--replace_ambig\", "
            "which is meant for files outputted by QIIME2 with SILVA "
            "taxonomy. When this option is set all labels containing "
            "\"uncultured\", \"Ambiguous_taxa\", \"metagenome\", or "
            "\"unidentified\", with \"Unclassified\". In addition, when this "
            "option is set it will also replace labels containing \"unknown\" "
            "with the preceeding label followed by \"_X\". Note that these "
            "labels are all case-insensitive.",

epilog='''Usage example: fix_spf.py -i otu_table.spf -o otu_table_fixed.spf''',

formatter_class=argparse.RawDescriptionHelpFormatter)

parser.add_argument("-i", "--input", help="Input STAMP file", required=True)

parser.add_argument("-o", "--output", help="Output fixed STAMP file",
                    required=True)

parser.add_argument("-c", "--col_count", required=False, default=7, type=int,
                    help="Number of columns in the file corresponding to "
                         "levels of interest (default=7). These should be "
                         "the first columns of the file and would typically "
                         "correspond to taxonomic levels such as Kingdom, "
                         "Phylum, etc.")

parser.add_argument("--replace_ambig", required=False, default=False,
                    action='store_true',
                    help="When set all ambiguous labels (see script "
                         "description) will be replaced with "
                         "\"Unclassified\". In addition, when this option is "
                         "set it will also replace labels containing "
                         "\"unknown\" with the preceeding label followed by "
                         "\"X\".")


def replace_ambig_labels(in_spf, out_spf, col_count):
    '''Function to read in a SPF and to replace all labels containing
    "uncultured", "Ambiguous_taxa", "metagenome", or "unidentified", with
    "Unclassified". In addition, when this option is set it will also replace
    labels containing "unknown with the preceeding label followed by "X". Will
    write out the new SPF.'''

    outfile = open(out_spf, "w")
    out_writer = csv.writer(outfile, delimiter="\t", lineterminator="\n")

    str2replace = ['uncultured', 'ambiguous_taxa', 'metagenome',
                   'unidentified']

    header_marker = 0

    with open(in_spf, "r") as infile:

        for line in infile:

            # Remove newline character and split by tab.
            line = line.rstrip("\r\n")
            line_split = line.split("\t")

            # Print out header and go to next line.
            if header_marker == 0:
                header_marker += 1
                outfile.write(line + "\n")
                continue

            # If no labels are in the set to replace then print out line and
            # move to next one.
            str_matches = 0

            for s in str2replace + ['unknown']:
                if s in line.lower():
                    str_matches += 1

            if str_matches == 0:
                outfile.write(line + "\n")
                continue

            # Get list of all taxonomic levels.
            taxa = line_split[0:col_count]

            # Loop through taxa and replace any ids in set of strings to
            # replace with "Unclassified". For any taxa containing "unknown",
            # replace these ids with the preceeding taxonomic level, but with
            # the correct DX level and followed by "_X".
            out_taxa = []

            # Loop over each label (from higher to lower levels).
            for label_i, label in enumerate(taxa):
                str_match = False

                for s in str2replace:
                    if s in label.lower():
                        str_match = True
                        break

                if str_match:
                    out_taxa.append('Unclassified')

                elif 'unknown' in label.lower():
                    pre_label_i = label_i - 1

                    if pre_label_i < 0 or out_taxa[pre_label_i] == 'Unclassified':
                        out_taxa.append('Unclassified')
                    else:
                        pre_label_search = re.search(r"D_\d+__(.*)",
                                                     out_taxa[pre_label_i])
                        pre_label_taxon = pre_label_search.group(1)
                        label_level = re.match(r"D_\d+__", label).group(0)
                        out_taxa.append(label_level + pre_label_taxon + "_X")

                else:
                    out_taxa.append(label)

            line_split[0:col_count] = out_taxa
            out_writer.writerow(line_split)

    outfile.close()


def check_intermediate_unclassified(orig_spf, col_count):
    '''Check whether any higher levels are 'Unclassified' while lower levels
    are classified. Change label to be preceding with "X" for these levels or
    alternatively throw an error if even the top level is 'Unclassified'.
    Returns dataframe with either no changes if there are no intermediate
    unclassified labels or with filled in labels. Note that col_count refers to
    the number of taxonomic columns at the start of the file.'''

    max_col_i = col_count - 1

    # Making a copy of this dataframe because the pandas dataframe being iterated
    # over should not be modified.
    new_spf = orig_spf.copy()

    for row_i, row in orig_spf.iterrows():

        taxa = list(orig_spf.iloc[row_i, 0:max_col_i])

        unclassified_i = []
        classified_i = []

        for i, t in enumerate(taxa):
            if t == 'Unclassified':
                unclassified_i.append(i)
            else:
                classified_i.append(i)

        if unclassified_i and min(unclassified_i) < max(classified_i):

            # Check whether first level is classified or not.
            if taxa[0] == 'Unclassified':
                sys.exit("Stopping - first level of this lineage is Unclassified, "
                         "but lower levels are classified:\n" + " ".join(taxa))

            # For any cases of intermediate Unclassified labels, fill in the
            # nearest classified parent label followed by X's equal to the number
            # of steps away this classified label is.
            for unclass_i in unclassified_i:

                if unclass_i < max(classified_i):
                    current_i = unclass_i
                    unclassified_steps = 1

                    while current_i > 0:
                        current_i -= 1

                        if taxa[current_i] == 'Unclassified' or \
                           current_i not in classified_i:
                            unclassified_steps += 1
                            next
                        else:
                            taxa[unclass_i] = taxa[current_i] + "_" + "X" * unclassified_steps
                            break

        new_spf.iloc[row_i, 0:max_col_i] = taxa

    return(new_spf)


def force_strict_spf_hierarchy(in_spf, col_count):
    '''Read through pandas df (of SPF file) and check that all levels form
    a strict hierarchy. Returns fixed df with "_dupN" added to the end of
    identical children with different parents. Note that col_count refers to
    the number of taxonomic columns at the start of the file.'''

    # Loop over all columns with labels.
    for i in range(col_count):

        # Skip first column.
        if i == 0:
            continue

        current_col = in_spf.columns[i]
        prior_col = in_spf.columns[i - 1]
        unique_labels = in_spf[current_col].unique()

        for label in unique_labels:

            # Skip Unclassified labels.
            if label == "Unclassified":
                continue

            matching_rows = in_spf[current_col] == label

            # Skip if only 1 matching row.
            if np.sum(matching_rows) == 1:
                continue

            # Otherwise check whether all the parents are identical.
            unique_parents = in_spf.loc[in_spf[current_col] == label, prior_col].unique()

            # If multiple parents (i.e. not a strict hierarchy) then add
            # "_dupN" to all children with different parents, where N is the
            # parent's index in the above list.
            if len(unique_parents) > 1:
                for idx, p in enumerate(unique_parents):
                    new_label = label + "_dup" + str(idx)

                    # Identify rows matching the label and parent value of
                    # interest.
                    rows2change = np.logical_and(matching_rows,
                                                 in_spf[prior_col] == p)

                    in_spf.loc[rows2change, current_col] = new_label

    return(in_spf)


def main():

    args = parser.parse_args()

    if args.replace_ambig:
        # Replace ambiguous labels and write out to temp directory.
        # Note that this is done since the two functions used for cleaning up
        # the SPF were not originally written to be used together.
        with TemporaryDirectory() as temp_dir:
            tmp_spf = path.join(temp_dir, "tmp_spf")
            replace_ambig_labels(args.input, tmp_spf, args.col_count)

            # Read in SPF file after replacing ambiguous labels.
            input_spf = pd.read_csv(filepath_or_buffer=tmp_spf, sep='\t')

    else:
        input_spf = pd.read_csv(filepath_or_buffer=args.input, sep='\t')

    # Check and add in strict hierarchy of SPF levels and write out table.
    input_spf = force_strict_spf_hierarchy(input_spf, args.col_count)

    # Check whether any higher levels are 'Unclassified' while lower
    # levels are classified. Fill in different labels if needed.
    input_spf = check_intermediate_unclassified(input_spf, args.col_count)

    input_spf.to_csv(path_or_buf=args.output, sep='\t', header=True,
                     index=False)


if __name__ == "__main__":
    main()
