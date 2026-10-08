// Collection level schema validation for the records that must never drift.
// Application level rules (hierarchy integrity, dependency cycles, approval
// cascade) are enforced in the service layer; these are the storage invariants.
const database = db.getSiblingDB(process.env.MONGO_INITDB_DATABASE || 'ai_analysis_team');

database.createCollection('projects', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['_id', 'key', 'name'],
      properties: {
        key: { bsonType: 'string', minLength: 1 },
        name: { bsonType: 'string', minLength: 1 },
        currency: { bsonType: 'string' },
      },
    },
  },
  validationLevel: 'moderate',
});

database.createCollection('approvalEvents', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['_id', 'projectId', 'manifestHash', 'decision', 'decidedBy'],
      properties: {
        decision: { enum: ['approve', 'reject'] },
        committed: { bsonType: 'bool' },
      },
    },
  },
  validationLevel: 'moderate',
});

database.createCollection('artifactVersions', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['_id', 'projectId', 'itemId', 'version', 'state'],
      properties: {
        version: { bsonType: 'int', minimum: 1 },
        state: {
          enum: ['draft', 'in_review', 'approved', 'rejected', 'superseded', 'archived'],
        },
      },
    },
  },
  validationLevel: 'moderate',
});

print('schema validation configured');
