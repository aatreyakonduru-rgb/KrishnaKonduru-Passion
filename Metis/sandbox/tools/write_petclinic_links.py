"""Writes the petclinic links file (the AI step in Metis, done by hand from the lines read)."""
import os
import sys

import yaml

P = "spring-petclinic/src/main/java/org/springframework/samples/petclinic/"
S = "spring-petclinic/src/main/resources/db/h2/schema.sql"
OC, PC, VC, VETC = (P + "owner/OwnerController.java", P + "owner/PetController.java",
                    P + "owner/VisitController.java", P + "vet/VetController.java")


def L(ft, fn, rel, tt, tn, src, line, quote):
    return {"from": {"type": ft, "name": fn}, "rel": rel, "to": {"type": tt, "name": tn},
            "source": '[E: %s:%d "%s"]' % (src, line, quote)}


links = [
    # endpoints -> controllers
    L("endpoint", "GET /owners", "handled_by", "class", "OwnerController", OC, 94, '@GetMapping("/owners")'),
    L("endpoint", "GET /owners/{ownerId}", "handled_by", "class", "OwnerController", OC, 178, '@GetMapping("/owners/{ownerId}")'),
    L("endpoint", "POST /owners/new", "handled_by", "class", "OwnerController", OC, 77, '@PostMapping("/owners/new")'),
    L("endpoint", "POST /owners/{ownerId}/edit", "handled_by", "class", "OwnerController", OC, 153, '@PostMapping("/owners/{ownerId}/edit")'),
    L("endpoint", "POST /owners/{ownerId}/pets/new", "handled_by", "class", "PetController", PC, 107, '@PostMapping("/pets/new")'),
    L("endpoint", "POST /owners/{ownerId}/pets/{petId}/edit", "handled_by", "class", "PetController", PC, 144, '@PostMapping("/pets/{petId}/edit")'),
    L("endpoint", "POST /owners/{ownerId}/pets/{petId}/visits/new", "handled_by", "class", "VisitController", VC, 97, '@PostMapping("/owners/{ownerId}/pets/{petId}/visits/new")'),
    L("endpoint", "GET /vets.html", "handled_by", "class", "VetController", VETC, 45, '@GetMapping("/vets.html")'),
    L("endpoint", "GET /vets", "handled_by", "class", "VetController", VETC, 72, '@GetMapping({ "/vets" })'),
    # controllers -> repositories
    L("class", "OwnerController", "uses", "class", "OwnerRepository", OC, 53, "private final OwnerRepository owners"),
    L("class", "PetController", "uses", "class", "OwnerRepository", PC, 53, "private final OwnerRepository owners"),
    L("class", "PetController", "uses", "class", "PetTypeRepository", PC, 55, "private final PetTypeRepository types"),
    L("class", "VisitController", "uses", "class", "OwnerRepository", VC, 45, "private final OwnerRepository owners"),
    L("class", "VetController", "uses", "class", "VetRepository", VETC, 39, "private final VetRepository vetRepository"),
    # writes by controller (cascade from Owner saves pets and visits)
    L("class", "OwnerController", "writes", "class", "Owner", OC, 84, "this.owners.save(owner)"),
    L("class", "PetController", "writes", "class", "Owner", PC, 126, "this.owners.saveAndFlush(owner)"),
    L("class", "VisitController", "writes", "class", "Owner", VC, 109, "this.owners.save(owner)"),
    # repositories -> entities
    L("class", "OwnerRepository", "manages", "class", "Owner", P + "owner/OwnerRepository.java", 36, "JpaRepository<Owner, Integer>"),
    L("class", "PetTypeRepository", "manages", "class", "PetType", P + "owner/PetTypeRepository.java", 30, "JpaRepository<PetType, Integer>"),
    L("class", "VetRepository", "manages", "class", "Vet", P + "vet/VetRepository.java", 38, "Repository<Vet, Integer>"),
    # entities -> tables
    L("class", "Owner", "maps_to", "table", "owners", P + "owner/Owner.java", 49, '@Table(name = "owners")'),
    L("class", "Pet", "maps_to", "table", "pets", P + "owner/Pet.java", 45, '@Table(name = "pets")'),
    L("class", "PetType", "maps_to", "table", "types", P + "owner/PetType.java", 27, '@Table(name = "types")'),
    L("class", "Visit", "maps_to", "table", "visits", P + "owner/Visit.java", 36, '@Table(name = "visits")'),
    L("class", "Vet", "maps_to", "table", "vets", P + "vet/Vet.java", 44, '@Table(name = "vets")'),
    L("class", "Specialty", "maps_to", "table", "specialties", P + "vet/Specialty.java", 29, '@Table(name = "specialties")'),
    # entity relationships
    L("class", "Owner", "contains", "class", "Pet", P + "owner/Owner.java", 70, "private final List<Pet> pets"),
    L("class", "Pet", "contains", "class", "Visit", P + "owner/Pet.java", 59, "private final Set<Visit> visits"),
    L("class", "Vet", "contains", "class", "Specialty", P + "vet/Vet.java", 50, "private Set<Specialty> specialties"),
    # foreign keys
    L("table", "pets", "references", "table", "owners", S, 53, "FOREIGN KEY (owner_id) REFERENCES owners (id)"),
    L("table", "pets", "references", "table", "types", S, 54, "FOREIGN KEY (type_id) REFERENCES types (id)"),
    L("table", "visits", "references", "table", "pets", S, 64, "FOREIGN KEY (pet_id) REFERENCES pets (id)"),
    L("table", "vet_specialties", "references", "table", "vets", S, 27, "FOREIGN KEY (vet_id) REFERENCES vets (id)"),
    L("table", "vet_specialties", "references", "table", "specialties", S, 28, "FOREIGN KEY (specialty_id) REFERENCES specialties (id)"),
    L("class", "Vet", "maps_to", "table", "vet_specialties", P + "vet/Vet.java", 48, '@JoinTable(name = "vet_specialties"'),
]

out = sys.argv[1]
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as fh:
    yaml.safe_dump({"links": links}, fh, sort_keys=False, width=250)
print("wrote %d links" % len(links))
