---
title: "Jour 3 — TCP : établissement de connexion (three-way handshake)"
subtitle: "Réseaux"
date: "18 novembre 2026"
---

## Résumé

Ce cours ouvre l'étude de la couche transport (couche 4 du modèle OSI), annoncée au cours précédent. Le prof a présenté la façon dont **TCP établit une connexion** grâce au **three-way handshake** (« poignée de main en trois temps »). Le client envoie d'abord un segment **SYN** avec un numéro de séquence initial. Le serveur répond par un **SYN-ACK** qui contient son propre numéro de séquence. Le client conclut avec un **ACK**. Pour fermer la connexion, on utilise des segments **FIN**. Le prof a dit que les trois étapes du handshake **tombent à l'examen**.

## Lien avec les cours précédents

- **Jour 1** (`Jour 1.md`) : les notions de base (réseau, protocole, latence) restent valables. TCP est un *protocole* de la couche transport, et le handshake ajoute un aller-retour de latence avant tout échange de données.
- **Jour 2** (`Jour 2.md`) : on a vu les 7 couches du modèle OSI, avec la couche transport (4) qui assure la communication **de bout en bout** grâce à TCP et UDP. La fiche du Jour 2 annonçait « TCP en détail » pour ce cours : on y est. Le modèle OSI n'est pas réexpliqué ici, voir `Jour 2.md`.

## Notions clés

Couche transport
:   Couche 4 du modèle OSI. Elle assure la communication de bout en bout entre deux applications (voir `Jour 2.md`).

TCP (Transmission Control Protocol)
:   Protocole de transport **orienté connexion** : une connexion doit être établie avant tout échange de données, puis fermée à la fin.

Segment
:   Unité de données de la couche transport (TCP). Les messages SYN, SYN-ACK, ACK et FIN sont des segments.

Numéro de séquence initial (ISN, *Initial Sequence Number*)
:   Numéro choisi par chaque extrémité au début de la connexion. Il sert de point de départ pour numéroter les octets envoyés.

SYN (*synchronize*)
:   Segment, ou drapeau, qui demande l'ouverture d'une connexion et transmet le numéro de séquence initial de l'émetteur.

ACK (*acknowledgment*)
:   Segment, ou drapeau, d'acquittement : il confirme la réception de ce que l'autre extrémité a envoyé.

SYN-ACK
:   Réponse du serveur au SYN. Elle acquitte le SYN du client et envoie en même temps le numéro de séquence initial du serveur.

Three-way handshake
:   Procédure d'ouverture d'une connexion TCP en trois échanges : SYN, puis SYN-ACK, puis ACK.

FIN (*finish*)
:   Segment, ou drapeau, utilisé pour fermer une connexion TCP.

## La couche transport et TCP

Le prof a fait le lien avec le cours précédent : après la vue d'ensemble du modèle OSI, on attaque la couche transport, en commençant par TCP.

TCP est **orienté connexion**. Contrairement à un envoi « direct », les deux machines doivent d'abord se mettre d'accord pour communiquer. Elles s'échangent notamment leurs numéros de séquence initiaux. C'est le rôle du three-way handshake.

## Établissement d'une connexion : le three-way handshake

Le handshake a lieu entre un **client**, qui ouvre la connexion, et un **serveur**, qui l'accepte. Il se fait en trois étapes.

### Étape 1 : SYN (client vers serveur)

Le client envoie un segment **SYN** qui contient son **numéro de séquence initial**. Cela revient à dire : « je veux ouvrir une connexion, et je commence ma numérotation à x ».

### Étape 2 : SYN-ACK (serveur vers client)

Le serveur répond par un segment **SYN-ACK** :

- la partie **ACK** acquitte le SYN du client ;
- la partie **SYN** transmet le **propre numéro de séquence initial du serveur**.

### Étape 3 : ACK (client vers serveur)

Le client termine avec un segment **ACK**, qui acquitte le SYN du serveur. La connexion est alors **établie** et les données peuvent circuler dans les deux sens.

### Schéma de l'échange

Le schéma est décrit en texte : le temps s'écoule de haut en bas.

```text
   Client                                Serveur
     |                                      |
     | ---- SYN (seq = x) ----------------> |   1. demande d'ouverture
     |                                      |
     | <--- SYN-ACK (seq = y, ack = x+1) -- |   2. acquittement + ISN du serveur
     |                                      |
     | ---- ACK (ack = y+1) --------------> |   3. confirmation
     |                                      |
     |        connexion établie             |
```

Précision ajoutée, qui n'a pas été détaillée à l'oral : dans TCP, la valeur d'acquittement vaut le numéro de séquence reçu **+ 1**. C'est pourquoi le schéma indique `ack = x+1` et `ack = y+1`.

### Récapitulatif

| Étape | Émetteur | Destinataire | Segment | Contenu essentiel |
|:-----:|:---------|:-------------|:--------|:------------------|
| 1 | Client | Serveur | SYN | ISN du client |
| 2 | Serveur | Client | SYN-ACK | Acquittement + ISN du serveur |
| 3 | Client | Serveur | ACK | Acquittement de l'ISN du serveur |

## Fermeture d'une connexion

À la fin d'une connexion, on utilise des segments **FIN**. Le prof n'a pas détaillé la séquence de fermeture pendant ce cours.

## Ce que le prof a souligné

- **« Retenez bien ces trois étapes, ça tombe à l'examen »** : il faut savoir donner l'ordre SYN → SYN-ACK → ACK, dire qui envoie chaque segment (client ou serveur) et ce qu'il contient (numéros de séquence initiaux).
- Le serveur envoie **son propre** numéro de séquence dans le SYN-ACK. Chaque côté a donc son ISN.
- La fermeture d'une connexion utilise des segments **FIN** (à distinguer de SYN, qui sert à l'ouverture).

## Questions de révision

1. À quelle couche du modèle OSI appartient TCP ?
   *À la couche transport (couche 4), qui assure la communication de bout en bout.*
2. Comment s'appelle la procédure d'ouverture d'une connexion TCP ?
   *Le three-way handshake (poignée de main en trois temps).*
3. Donnez dans l'ordre les trois segments du handshake.
   *SYN (client → serveur), SYN-ACK (serveur → client), ACK (client → serveur).*
4. Que contient le premier segment SYN envoyé par le client ?
   *Le numéro de séquence initial (ISN) du client.*
5. Quel est le double rôle du segment SYN-ACK ?
   *Il acquitte le SYN du client (ACK) et transmet le numéro de séquence initial du serveur (SYN).*
6. Pourquoi le client doit-il envoyer un ACK final ?
   *Pour acquitter le SYN du serveur. Sans cet ACK, le serveur ne sait pas que son ISN a bien été reçu, et la connexion n'est pas établie.*
7. Quel type de segment sert à fermer une connexion TCP ?
   *Les segments FIN.*
8. Si le client envoie un SYN avec `seq = 100` et que le serveur choisit `seq = 300`, que contient le SYN-ACK ?
   *`seq = 300` et `ack = 101` ; le client répond ensuite par un ACK avec `ack = 301`.*

## Compléments ajoutés

Ce cours a aussi complété d'autres fichiers du dossier :

- complété : Jour 2.md
