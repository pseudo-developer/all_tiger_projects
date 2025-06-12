curl https://packages.microsoft.com/keys/microsoft.asc | sudo tee /etc/apt/trusted.gpg.d/microsoft.asc
sudo curl https://packages.microsoft.com/config/ubuntu/20.04/prod.list > /tmp/prod.list
sudo cp /tmp/prod.list /etc/apt/sources.list.d/mssql-release.list
echo "installing ubuntu packages"
until sudo apt-get -y update && sudo ACCEPT_EULA=Y apt-get install jq unzip mssql-tools18 unixodbc-dev -y
do
  echo "Waiting until apt lock is released"
  sleep 2
done
echo "finished installing ubuntu packages"
echo "installing az"
until curl -vsL https://aka.ms/InstallAzureCLIDeb | sudo bash
do
   echo "Waiting until apt lock is released"
   sleep 2
done
echo "finished installing azure cli"
