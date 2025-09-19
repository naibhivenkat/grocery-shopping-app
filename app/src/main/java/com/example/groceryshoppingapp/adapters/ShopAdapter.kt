package com.example.groceryshoppingapp.adapters

import android.content.Context
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.BaseAdapter
import android.widget.TextView
import com.example.groceryshoppingapp.R
import com.example.groceryshoppingapp.models.Shop

class ShopAdapter(private val context: Context, private val shopList: List<Shop>) : BaseAdapter() {

    override fun getCount(): Int = shopList.size

    override fun getItem(position: Int): Any = shopList[position]

    // 🔑 Fix: use position or hashCode() instead of toLong()
    override fun getItemId(position: Int): Long {
        return shopList[position].id.hashCode().toLong()  // stable + unique
        // Or simply: return position.toLong()
    }

    override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
        val view: View = convertView ?: LayoutInflater.from(context).inflate(R.layout.item_shop, parent, false)

        val shop = shopList[position]
        val nameTextView = view.findViewById<TextView>(R.id.shop_name)
        val addressTextView = view.findViewById<TextView>(R.id.shop_address)

        nameTextView.text = shop.name
        addressTextView.text = shop.address

        return view
    }
}
