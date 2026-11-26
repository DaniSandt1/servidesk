// Resolver de Serverless (${file(./vpc.js):...}): busca la VPC por defecto de la cuenta y dos
// zonas de disponibilidad (las 2 primeras con subred por defecto, sin us-east-1e) para crear ahí
// las subredes privadas. Así el template funciona en la cuenta de cualquier integrante sin IDs fijos.
const AWS = require('aws-sdk');

module.exports = async ({ resolveVariable }) => {
  const region = await resolveVariable('self:provider.region');
  const ec2 = new AWS.EC2({ region });

  const { Vpcs } = await ec2.describeVpcs({ Filters: [{ Name: 'is-default', Values: ['true'] }] }).promise();
  if (!Vpcs.length) throw new Error(`No hay VPC por defecto en ${region}`);
  const vpcId = Vpcs[0].VpcId;

  const { Subnets } = await ec2.describeSubnets({
    Filters: [{ Name: 'vpc-id', Values: [vpcId] }, { Name: 'default-for-az', Values: ['true'] }],
  }).promise();
  const azs = Subnets.map((s) => s.AvailabilityZone)
    .filter((az) => !az.endsWith('e')) // us-east-1e no soporta todos los servicios
    .sort()
    .slice(0, 2);
  if (azs.length < 2) throw new Error('Se necesitan 2 zonas de disponibilidad');

  return { vpcId, azA: azs[0], azB: azs[1] };
};
