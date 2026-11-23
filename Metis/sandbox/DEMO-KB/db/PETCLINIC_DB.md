# Pet Clinic database

## Tables [E: spring-petclinic/src/main/resources/db/h2/schema.sql:10-65]

The schema file creates seven tables: vets, specialties, vet_specialties, types, owners, pets and visits. [E: spring-petclinic/src/main/resources/db/h2/schema.sql:10 "CREATE TABLE vets"]

The pets table has a foreign key to owners. [E: spring-petclinic/src/main/resources/db/h2/schema.sql:53 "FOREIGN KEY (owner_id) REFERENCES owners (id)"]

The pets table has a foreign key to types. [E: spring-petclinic/src/main/resources/db/h2/schema.sql:54 "FOREIGN KEY (type_id) REFERENCES types (id)"]

The visits table has a foreign key to pets. [E: spring-petclinic/src/main/resources/db/h2/schema.sql:64 "FOREIGN KEY (pet_id) REFERENCES pets (id)"]

An owner cannot have two pets with the same name. [E: spring-petclinic/src/main/resources/db/h2/schema.sql:55 "UNIQUE (owner_id, name)"]

The owners.last_name column is case-insensitive. [E: spring-petclinic/src/main/resources/db/h2/schema.sql:39 "VARCHAR_IGNORECASE(30)"]

## Open questions

Which database engine runs in production? Only the H2 schema was read for this build. [?: Q-0001]
