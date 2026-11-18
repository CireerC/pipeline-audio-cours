# Prompt de standardisation — md2pdf

Redige un rapport en Markdown (.md) compatible avec le systeme md2pdf (Pandoc + XeLaTeX).

## Compilation

```bash
python convert.py rapport.md -m academic -t ./theme
python convert.py rapport.md -m light
```

## Frontmatter YAML

Commence le fichier par un bloc YAML entre `---`. Seul `title` est obligatoire.

```yaml
---
title: "Titre du rapport"
subtitle: "Sous-titre"
author: "Prenom Nom"
date: "12 juin 2026"
school: "ecole"
specialty: "Informatique"
professor: "M. Prof"
client: "Entreprise"
logo: "logo-ecole.png"
logo-secondary: "logo-universite.png"
logo-left: "logo-universite.png"
logo-right: "logo-ecole.png"
cover-background: "fond-couverture.png"
page-background: "fond-page.png"
---
```

## Titres

- `##` = section principale (1, 2, 3...)
- `###` = sous-section (1.1, 1.2...)
- `####` = sous-sous-section
- Ne jamais utiliser `#` dans le corps
- Toujours mettre du texte entre deux titres

## Syntaxe supportee

**Texte** : `**gras**`, `*italique*`, `~~barre~~`, `` `code` ``, `x^exp^`, `H~ind~`, `[lien](url)`, `[^1]` (note de bas de page)

**Code** : toujours specifier le langage (un label apparait automatiquement). Les lignes longues sont coupees avec ↪.

````markdown
```python
def hello():
    print("Bonjour")
```
````

**Maths** : inline `$E = mc^2$`, bloc `$$E = mc^2$$`

**Tableaux** : 6 colonnes max. Alignement avec `:` dans la ligne de separation.

```markdown
| Gauche | Centre | Droite |
|:-------|:------:|-------:|
| a      | b      | c      |
```

**Images** : `![Legende](image.png)` ou `![Legende](image.png){width=80%}`

**Listes** : `-` (puces), `1.` (numerotees), `- [x]` (taches), `Terme` + `:   Definition`

**Citations** : `> texte de la citation`

## Regles

- Pas de `#` dans le corps, pas de HTML, pas de `---` entre les sections
- Blocs de code : toujours specifier le langage
