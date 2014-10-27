# Provision a Deis Cluster on Amazon EC2

## Install the [AWS Command Line Interface][aws-cli]:
```console
$ pip install awscli
Downloading/unpacking awscli
  Downloading awscli-1.5.0.tar.gz (248kB): 248kB downloaded
...
Successfully installed awscli
```

## Configure aws-cli
Run `aws configure` to set your AWS credentials:
```console
$ aws configure
AWS Access Key ID [None]: ***************
AWS Secret Access Key [None]: ************************
Default region name [None]: us-west-1
Default output format [None]:
```

## Upload keys
Generate and upload a new keypair to AWS, ensuring that the name of the keypair is set to "deis".
```console
$ ssh-keygen -q -t rsa -f ~/.ssh/deis -N '' -C deis
$ aws ec2 import-key-pair --key-name deis --public-key-material file://~/.ssh/deis.pub
```

## Choose number of instances
By default, the script will provision 3 servers. You can override this by setting `DEIS_NUM_INSTANCES`:
```console
$ export DEIS_NUM_INSTANCES=5
```

Note that for scheduling to work properly, clusters must consist of at least 3 nodes and always have an odd number of members.
For more information, see [optimal etcd cluster size](https://github.com/coreos/etcd/blob/master/Documentation/optimal-cluster-size.md).

Deis clusters of less than 3 nodes are unsupported.

## Customize user-data

Create a user-data file with a new discovery URL this way:

```console
$ make discovery-url
```

Or copy [`contrib/coreos/user-data.example`](../coreos/user-data.example) to `contrib/coreos/user-data` and follow the directions in the `etcd:` section to add a unique discovery URL.

## Customize cloudformation.json
Any of the parameter defaults defined in deis.template.json can be overridden
by setting the value in [cloudformation.json](cloudformation.json) like so:

```
    {
        "ParameterKey":     "InstanceType",
        "ParameterValue":   "m3.xlarge"
    },
    {
        "ParameterKey":     "KeyPair",
        "ParameterValue":   "jsmith"
    },
    {
        "ParameterKey":     "EC2VirtualizationType",
        "ParameterValue":   "PV"
    },
    {
        "ParameterKey":     "AssociatePublicIP",
        "ParameterValue":   "false"
    }
```

The only entry in cloudformation.json required to launch your cluster is `KeyPair`,
which is already filled out. The defaults will be applied for the other settings.

If updated with update-ec2-cluster.sh, the InstanceType will only impact newly deployed instances (#1758).

NOTE: The smallest recommended instance size is `large`. Having not enough CPU or RAM will result
in numerous issues when using the cluster.

## Launch into an existing VPC
By default, the provided CloudFormation script will create a new VPC for Deis. However, the script
supports provisioning into an existing VPC instead. You'll need to have a VPC configured with an
internet gateway and a sane routing table (the default VPC in a region should be ready to go).

To launch your cluster into an existing VPC, export three additional environment variables: ```VPC_ID```,
```VPC_SUBNETS```, ```VPC_ZONES```. ```VPC_ZONES``` must list the availability zones of the
subnets in order.

For example, if your VPC has ID ```vpc-a26218bf``` and consists of the subnets ```subnet-04d7f942```
(which is in ```us-east-1b```) and ```subnet-2b03ab7f``` (which is in ```us-east-1c```) you would
export:

```
export VPC_ID=vpc-a26218bf
export VPC_SUBNETS=subnet-04d7f942,subnet-2b03ab7f
export VPC_ZONES=us-east-1b,us-east-1c
```

## Run the provision script
Run the [cloudformation provision script][pro-script] to spawn a new CoreOS cluster:
```console
$ cd contrib/ec2
$ ./provision-ec2-cluster.sh
{
    "StackId": "arn:aws:cloudformation:us-west-1:413516094235:stack/deis/9699ec20-c257-11e3-99eb-50fa01cd4496"
}
Your Deis cluster has successfully deployed.
Please wait for all instances to come up as "running" before continuing.
```

Check the AWS EC2 web control panel and wait until "Status Checks" for all instances have passed.
This will take several minutes.

## Configure Deis
Set the default domain used to anchor your applications:

```console
$ deisctl config platform set domain=mycluster.local
```

For this to work, you'll need to configure DNS records so you can access applications hosted on Deis. See [Configuring DNS](http://docs.deis.io/en/latest/installing_deis/configure-dns/) for details.

If you want to allow `deis run` for one-off admin commands, you must provide an SSH private key that allows Deis to gather container logs on CoreOS hosts:

```console
$ deisctl config platform set sshPrivateKey=<path-to-private-key>
```

## Initialize the cluster
Once the cluster is up, get the hostname of any of the machines from EC2, set
DEISCTL_TUNNEL, and issue a `deisctl install`:
```console
$ ssh-add ~/.ssh/deis
$ export DEISCTL_TUNNEL=ec2-12-345-678-90.us-west-1.compute.amazonaws.com
$ deisctl install platform && deisctl start platform
```
Deisctl will deploy Deis and make sure the services start properly.

## Configure load balancer
The Deis provisioning scripts for EC2 automatically create an Elastic Load Balancer for your Deis
cluster. However, ELBs on EC2 have a default timeout of 60 seconds, which will disrupt a ``git push``
when using Deis. You should manually [increase this timeout](http://docs.aws.amazon.com/ElasticLoadBalancing/latest/DeveloperGuide/config-idle-timeout.html)
to 1200 seconds to match the timeout on the router and application unit files.

## Configure DNS
While you can reference the controller and hosted applications with public hostnames provided by EC2, it is recommended for ease-of-use that
you configure your own DNS records using a domain you own. See [Configuring DNS](http://docs.deis.io/en/latest/installing_deis/configure-dns/) for details.

## Use Deis!
After that, register with Deis!
```console
$ deis register http://deis.example.org
username: deis
password:
password (confirm):
email: info@opdemand.com
```

## Hack on Deis

See [Hacking on Deis](http://docs.deis.io/en/latest/contributing/hacking/).

[aws-cli]: https://github.com/aws/aws-cli
[template]: https://s3.amazonaws.com/coreos.com/dist/aws/coreos-alpha.template
[pro-script]: provision-ec2-cluster.sh
