import re

with open('cas-dc-template.tex', 'r') as f:
    text = f.read()

# Helper to extract a block
def extract_env(env_name, text):
    blocks = []
    pattern = r"\\begin\{" + env_name + r"\}.*?\\end\{" + env_name + r"\}"
    for match in re.finditer(pattern, text, re.DOTALL):
        blocks.append(match.group(0))
    # remove them from text
    text_new = re.sub(pattern, "", text, flags=re.DOTALL)
    # clean multiple blank lines created by removal
    text_new = re.sub(r'\n{3,}', '\n\n', text_new)
    return blocks, text_new

# Extract all figure, figure*, table, table* environments
fig_blocks, text = extract_env(r"figure", text)
fig_star_blocks, text = extract_env(r"figure\*", text)
tab_blocks, text = extract_env(r"table", text)
tab_star_blocks, text = extract_env(r"table\*", text)

all_floats = fig_blocks + fig_star_blocks + tab_blocks + tab_star_blocks

# We want to place each float right after the paragraph where it's first referenced.
# If it's not referenced, we will place it strategically.
# First, identify the \label in each float block
floats_by_label = {}
for blk in all_floats:
    # also identify the label
    m = re.search(r'\\label\{([^}]+)\}', blk)
    if m:
        floats_by_label[m.group(1)] = blk
    else:
        print("Float without label found! Snippet:", blk[:50])

# Add missing references into text
# fig:framework_arch is the proposed framework architecture.
# We should reference it in section Proposed Framework (Section 6)
if "The full SustainSched-MPC optimization problem" in text:
    text = text.replace(r"\section{Proposed Framework}", 
                        "\\section{Proposed Framework}\n\\label{sec:framework}\nFigure~\\ref{fig:framework_arch} illustrates the high-level architecture of SustainSched-MPC.\n")

# fig:overhead_cdf shows scheduling overhead CDF.
# We should reference it in the Complexity section or Analysis section where overhead is discussed.
if "The observed \\emph{wall-clock} scheduling overhead" in text:
    text = text.replace(r"The observed \emph{wall-clock} scheduling overhead of 2.3\,s", 
                        r"As shown in Figure~\ref{fig:overhead_cdf}, the observed \emph{wall-clock} scheduling overhead of 2.3\,s")

# Let's rebuild the file placing each float right after its first \ref in the file.
# One pass over paragraphs.
pars = text.split('\n\n')
new_pars = []
inserted_labels = set()

# Special handling: don't place floats too early if it's just mentioning them abstractly in related work.
# Actually, standard rule: place the float after the paragraph where it is referred.
for par in pars:
    new_pars.append(par)
    
    # Check what labels are referenced in this paragraph
    # We want to insert the respective float blocks after this paragraph.
    refs_in_par = re.findall(r'\\ref\{([^}]+)\}', par)
    for ref in refs_in_par:
        if ref in floats_by_label and ref not in inserted_labels:
            # wait, tab:litreview is in related work, that's fine.
            # fig:daily_profile is first referenced in Section "Problem Formulation" (Eq 1). Let's let it be placed there.
            new_pars.append(floats_by_label[ref])
            inserted_labels.add(ref)

# Place any uninserted floats at the end before \end{document}
uninserted = []
for label, blk in floats_by_label.items():
    if label not in inserted_labels:
        # e.g., fig:exp_protocol
        # we placed it right at the end of sec 8, but it wasn't referenced.
        # Let's just append it. Or better, let's fix the reference.
        # Wait, fig:exp_protocol is referenced in the first line of section 8... oh, no it isn't.
        # Let's add it before \end{document} or something?
        uninserted.append(blk)

if uninserted:
    # insert them right before Conclusion
    for i, par in enumerate(new_pars):
        if "\\section{Conclusion}" in par:
            new_pars.insert(i, "\n".join(uninserted))
            break

text_new = "\n\n".join(new_pars)
with open('cas-dc-template.tex', 'w') as f:
    f.write(text_new)

print("Moved", len(floats_by_label), "floats toward their references.")

